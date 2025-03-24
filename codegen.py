import asyncio
from typing import Dict, List
from contextlib import AsyncExitStack
import json
import logging
import tiktoken
import time
from tenacity import retry, stop_after_attempt, wait_exponential
import httpx

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from anthropic import Anthropic
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global parameters
MAX_TOKENS = 8192
CONTEXT_WINDOW = 100000
MAX_RETRIES = 10
INITIAL_RETRY_DELAY = 10  # seconds
MAX_RETRY_DELAY = 60  # seconds

load_dotenv()  # load environment variables from .env

class MCPClient:
    def __init__(self):
        # Initialize session and client objects
        self.sessions: Dict[str, ClientSession] = {}
        self.tool_mapping: Dict[str, tuple] = {}  # Maps formatted tool names to (server_name, original_tool_name)
        self.exit_stack = AsyncExitStack()
        self.anthropic = Anthropic(api_key="your key")
        self.messages: List[dict] = []  # Store conversation history
        self.summary: List[dict] = []  # Store conversation summary
        self.encoding = tiktoken.encoding_for_model("gpt-3.5-turbo")  # Use GPT tokenizer as approximation

    def count_tokens(self, text: str) -> int:
        """Count tokens in text using tiktoken"""
        return len(self.encoding.encode(text))

    def manage_context_window(self, messages: List[dict]) -> List[dict]:
        """Ensure messages fit within context window by removing oldest messages if needed"""
        total_tokens = 0
        for message in reversed(messages):  # Start from most recent
            total_tokens += self.count_tokens(message["content"])
        
        while total_tokens > CONTEXT_WINDOW and len(messages) > 1:
            removed_msg = messages.pop(0)  # Remove oldest message
            total_tokens -= self.count_tokens(removed_msg["content"])
            logger.debug(f"Removed message from history to fit context window. Current tokens: {total_tokens}")

    async def load_server_config(self, config_path: str = "server.config"):
        """Load server configuration from file"""
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
                logger.info(f"Successfully loaded config from {config_path}")
                return config.get('mcpServers', {})
        except Exception as e:
            logger.error(f"Error loading config file: {str(e)}")
            return {}

    def format_tool_name(self, server_name: str, tool_name: str) -> str:
        """Format tool name to match the required pattern ^[a-zA-Z0-9_-]{1,64}$"""
        formatted_name = f"{server_name}_{tool_name}"
        # Replace any invalid characters with underscores
        formatted_name = ''.join(c if c.isalnum() or c in '_-' else '_' for c in formatted_name)
        return formatted_name[:64]  # Ensure name doesn't exceed 64 characters

    async def connect_to_servers(self):
        """Connect to all configured MCP servers"""
        server_configs = await self.load_server_config()
        logger.info(f"Found {len(server_configs)} servers in config")
        
        for server_name, config in server_configs.items():
            try:
                logger.debug(f"Attempting to connect to server '{server_name}' with config: {config}")
                command = config.get('command')
                args = config.get('args', [])
                env = config.get('env')
                
                server_params = StdioServerParameters(
                    command=command,
                    args=args,
                    env=env
                )
                
                stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
                stdio, write = stdio_transport
                session = await self.exit_stack.enter_async_context(ClientSession(stdio, write))
                
                await session.initialize()
                
                # Store session with server name
                self.sessions[server_name] = session
                
                # List available tools for this server
                response = await session.list_tools()
                tools = response.tools
                logger.info(f"Connected to server '{server_name}' with tools: {[tool.name for tool in tools]}")
                
            except Exception as e:
                logger.error(f"Failed to connect to server '{server_name}': {str(e)}")

    async def call_claude_api(self, messages, tools):
        """Make API call to Claude"""
        try:
            logger.debug("Making API call to Claude...")
            response = self.anthropic.messages.create(
                # model="claude-3-5-sonnet-20241022",
                model="claude-3-7-sonnet-20250219",
                max_tokens=MAX_TOKENS,
                messages=messages,
                system="""
                You are a code generation agent. Your role is to analyze the user's request and operate on the project by inspecting and modifying files as needed to fulfill the task.
                Remember to use filesystem tools to complete all necessary modifications. Each announced change should be followed by an immediate tool call.
                """,
                tools=tools
            )
            logger.debug(f"API call successful, request_id: {response.id}")
            return response
        except Exception as e:
            logger.error(f"Error in Claude API call: {str(e)}")
            raise

    async def analyze_query(self, query: str) -> str:
        """Analyze the query and generate a high-level plan"""
        analysis_prompt = f"""
            You are a code generation agent. Your role is to analyze the user's request and operate on the project located at /myproject by inspecting and modifying files as needed to fulfill the task.
            Your mission: Fulfill the following user request by executing a step-by-step, structured code generation workflow.

            User Request:
            {query}

            Your high-level plan must follow this workflow:

            1. Understand the Project Structure
            Retrieve the full directory structure of /myproject to understand how the project is organized.
            2. Identify Relevant Files
            List all files in the project.
            Identify files likely to be relevant to the request (based on file paths, names, or types).
            3. Analyze Existing Code
            Read the contents of the relevant files.
            Summarize or highlight code segments that are important or may need changes.
            4. Modify or Create Code
            Based on your analysis, modify existing files or create new files to implement the request.
            Ensure that any new or changed code integrates smoothly with the rest of the project.
            5. Preserve Functionality & Integrity
            Ensure your edits do not break existing functionality.

            Deliver your plan in a structured format so it can be followed directly for implementation.
        """

        try:
            response = await self.call_claude_api([{"role": "user", "content": analysis_prompt}], [])
            return response.content[0].text
        except Exception as e:
            logger.error(f"Error in query analysis: {str(e)}")
            raise

    @retry(
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=INITIAL_RETRY_DELAY, max=MAX_RETRY_DELAY),
        before_sleep=lambda retry_state: logger.info(f"Retrying process_query after {retry_state.next_action.sleep} seconds...")
    )
    async def process_query(self, query: str) -> str:
        """Process a code generation query using Claude and available tools"""
        logger.info(f"Processing query: {query}")
        logger.info("=== START OF QUERY PROCESSING ===")
        
        try:
            # Initialize iteration message with last summary item if available
            iteration_message = []
            if self.summary:
                iteration_message.append(self.summary[-1].copy())
                iteration_message.append(
                    {
                        "role": "user",
                        "content": "The previous response summarizes the last query. Use it for context and proceed with addressing the next request accordingly."
                    }
                )
                logger.debug("Copied last summary item to iteration_message")
            
            # Add user query to iteration message
            iteration_message.append({
                "role": "user",
                "content": query
            })
            
            # First, analyze the query and generate a plan
            logger.info("Analyzing query and generating plan...")
            # analysis_result = await self.analyze_query(query)
            logger.info("Query analysis completed")
            
            # Add analysis to iteration message
            iteration_message.extend([
                {
                    "role": "assistant",
                    "content": '''
                        I will provide a high-level plan to accomplish the request.
                        Project path: /myproject

                        - Obtaining the **directory structure** to understand the project's layout.
                        - **Listing** all files to identify relevant files.
                        - **Reading** the necessary files to analyze existing content.
                        - **Editing or creating files** as required.
                        - Ensuring that modifications integrate well with existing code without breaking functionality.
                    '''
                },
                {
                    "role": "user",
                    "content": "Please proceed with the implementation based on this analysis. Modify only one file at a time."
                }
            ])
            
            # Debug the iteration message before processing
            logger.debug("Iteration message before processing:")
            for msg in iteration_message:
                logger.debug(f"Role: {msg['role']}, Content: {msg['content'][:100]}...")

            # Collect tools from filesystem server
            all_tools = []
            self.tool_mapping.clear()
            
            session = self.sessions.get("filesystem")
            if session:
                try:
                    response = await session.list_tools()
                    for tool in response.tools:
                        formatted_name = self.format_tool_name("filesystem", tool.name)
                        self.tool_mapping[formatted_name] = ("filesystem", tool.name)
                        
                        tool_info = { 
                            "name": formatted_name,
                            "description": f"[filesystem] {tool.description}",
                            "input_schema": tool.inputSchema
                        }
                        all_tools.append(tool_info)
                        logger.debug(f"Added tool: {formatted_name} -> filesystem.{tool.name}")
                except Exception as e:
                    logger.error(f"Error collecting tools from filesystem server: {str(e)}")

            final_text = []
            current_assistant_message = []  # Buffer for building current assistant message
            loop_count = 0  # Add counter for loop iterations
            modified_code = ""
            
            while True:  # Continue processing until we get an end_turn
                loop_count += 1
                logger.info(f"=== STARTING LOOP ITERATION {loop_count} ===")
                logger.debug(f"Sending request to Claude with {len(all_tools)} tools")
                
                response = await self.call_claude_api(iteration_message, all_tools)
                logger.info(f"Response received - Stop reason: {response.stop_reason}")
                logger.info(f"Number of content items: {len(response.content)}")
                
                has_tool_call = False  # Flag to track if we've seen a tool call in this response
                logger.debug(f"Response: {response}")
                try:
                    # Process the response based on stop reason
                    for idx, content in enumerate(response.content):
                        logger.info(f"Processing content item {idx + 1}/{len(response.content)} of type: {content.type}")
                        
                        if content.type == 'text':
                            text_content = content.text
                            logger.debug(f"Received text content ({len(text_content)} chars): {text_content[:100]}...")
                            current_assistant_message.append(text_content)
                            final_text.append(text_content)
                            
                        elif content.type == 'tool_use':
                            has_tool_call = True
                            logger.info(f"Processing tool call in iteration {loop_count}")
                            # If we have accumulated any assistant message, add it to iteration message
                            if current_assistant_message:
                                assistant_msg = "\n".join(current_assistant_message)
                                logger.debug(f"Adding accumulated assistant message ({len(assistant_msg)} chars) before tool call")
                                iteration_message.append({
                                    "role": "assistant",
                                    "content": assistant_msg
                                })
                                current_assistant_message = []  # Clear the buffer
                                
                            formatted_tool_name = content.name
                            tool_args = content.input
                            logger.info(f"Tool call details - Name: {formatted_tool_name}, Args: {json.dumps(tool_args, indent=2)}")
                            
                            if formatted_tool_name in self.tool_mapping:
                                server_name, original_tool_name = self.tool_mapping[formatted_tool_name]
                                logger.debug(f"Mapped tool name: {original_tool_name} on server: {server_name}")
                                
                                if server_name in self.sessions:
                                    session = self.sessions[server_name]
                                    try:
                                        # Execute tool call
                                        logger.info(f"Executing tool {original_tool_name} on server {server_name}")
                                        result = await session.call_tool(original_tool_name, tool_args)
                                        logger.info("Tool execution completed")
                                        logger.debug(f"Raw tool result: {result}")
                                        
                                        # Process tool result
                                        result_content = ""
                                        if hasattr(result, 'content'):
                                            if isinstance(result.content, str):
                                                result_content = result.content
                                            else:
                                                result_content = str(result.content[0].text) if result.content[0].type == 'text' else str(result.content[0])
                                        else:
                                            result_content = str(result)
                                            logger.debug(f"Using str(result): {result_content}")

                                        if formatted_tool_name == "filesystem_edit_file":
                                            modified_code += result.content[0].text
                                        
                                        # Add tool call and result to final_text only
                                        final_text.append(f"[Calling tool {formatted_tool_name} with args {json.dumps(tool_args)}]")
                                        final_text.append(f"Tool result: {result_content[:200]}...")
                                        
                                        # Add tool result to iteration message
                                        tool_result_msg = {
                                            "role": "user",
                                            "content": f"""Tool execution completed:
                                            - Tool: {formatted_tool_name}
                                            - Status: Success
                                            - Result: {result_content}

                                        Please continue with the implementation. Make sure to complete all necessary file modifications."""
                                        }
                                        iteration_message.append(tool_result_msg)
                                        
                                        logger.info("Tool call and result processed")
                                        
                                    except Exception as e:
                                        error_msg = f"Error executing tool {formatted_tool_name}: {str(e)}"
                                        logger.error(error_msg)
                                        logger.error(f"Exception type: {type(e)}")
                                        logger.error(f"Exception details: {str(e)}")
                                        import traceback
                                        logger.error(f"Traceback: {traceback.format_exc()}")
                                        final_text.append(error_msg)
                                        raise  # Propagate the error for retry
                                else:
                                    error_msg = f"Error: Server '{server_name}' not connected"
                                    logger.error(error_msg)
                                    final_text.append(error_msg)
                                    raise Exception(error_msg)
                            else:
                                error_msg = f"Error: Unknown tool '{formatted_tool_name}'"
                                logger.error(error_msg)
                                final_text.append(error_msg)
                                raise Exception(error_msg)
                    
                    # After processing all content in this response
                    logger.info(f"Finished processing all content items in iteration {loop_count}")
                    logger.info(f"has_tool_call: {has_tool_call}, current_assistant_message length: {len(current_assistant_message)}")
                    
                    if current_assistant_message:  # Always add assistant messages to iteration message
                        assistant_msg = "\n".join(current_assistant_message)
                        logger.info(f"Adding assistant message to iteration message ({len(assistant_msg)} chars)")
                        iteration_message.append({
                            "role": "assistant",
                            "content": assistant_msg
                        })
                        current_assistant_message = []  # Clear the buffer
                    
                    # Break the loop if we get an end_turn or other terminal stop reason
                    if response.stop_reason in ['end_turn', 'max_tokens', 'stop_sequence']:
                        logger.info(f"=== BREAKING LOOP on iteration {loop_count} due to stop reason: {response.stop_reason} ===")
                        # Ensure any remaining assistant message is added to iteration message
                        if current_assistant_message:
                            assistant_msg = "\n".join(current_assistant_message)
                            logger.info(f"Adding final assistant message before break ({len(assistant_msg)} chars)")
                            iteration_message.append({
                                "role": "assistant",
                                "content": assistant_msg
                            })
                        break
                    else:
                        logger.info(f"=== CONTINUING TO NEXT ITERATION - Current stop reason: {response.stop_reason} ===")
                        
                except Exception as e:
                    logger.error(f"Error in iteration {loop_count}: {str(e)}")
                    raise  # Propagate the error for retry
            # Log iteration message details
            logger.info("Iteration messages:")
            for msg in iteration_message:
                content_preview = msg['content'][:1000] + '...' if len(msg['content']) > 1000 else msg['content']
                logger.info(f"[{msg['role']}]: {content_preview}")
            # After successful completion of all iterations, copy iteration message to self.messages
            self.messages.extend(iteration_message)
            logger.info("Successfully copied iteration message to main message history")

            # Perform verification
            verification_prompt = f"""
                You have just modified the following code:

                --- BEGIN MODIFIED CODE ---
                {modified_code if modified_code else "No code modifications were made in this session."}
                --- END MODIFIED CODE ---

                User's original request:
                {query}

                Please verify the following:
                1. Ensure that the modifications fully satisfy the user's request.
                2. Check that no existing functionalities have been broken.
                3. Validate the overall correctness of the changes, including syntax and logic.
                4. If any potential issues are detected, suggest necessary fixes.

                Provide a structured response in the following format:
                - Verification Status: [Pass / Needs Fixes]
                - Explanation: [Briefly explain whether the changes meet the requirements]
            """

            verification_response = await self.call_claude_api([{"role": "user", "content": verification_prompt}], [])
            verification_result = verification_response.content[0].text
            
            # Add verification result to final text and summary
            final_text.append("\n=== VERIFICATION RESULTS ===")
            final_text.append(verification_result)
            
            # Add verification result to summary
            summary = f"""
                User's original request:
                {query}

                You have just modified the following code:

                --- BEGIN MODIFIED CODE ---
                {modified_code if modified_code else "No code modifications were made in this session."}
                --- END MODIFIED CODE ---

                Verification result:
                {verification_result}
            """

            self.summary.append({
                "role": "assistant",
                "content": summary
            })
            
            logger.info("Verification completed and added to summary")
            logger.debug(f"Verification result: {verification_result}")

            logger.info("=== END OF QUERY PROCESSING ===")
            return "\n".join(final_text)
            
        except Exception as e:
            logger.error(f"Error in process_query: {str(e)}")
            raise  # Propagate the error for retry

    async def chat_loop(self):
        """Run an interactive chat loop"""
        print("\nMCP Client Started!")
        print("Type your queries or 'quit' to exit.")
        
        while True:
            try:
                query = input("\nQuery: ").strip()
                
                if query.lower() == 'quit':
                    break
                    
                response = await self.process_query(query)
                print("\n" + response)
                    
            except Exception as e:
                print(f"\nError: {str(e)}")
    
    async def cleanup(self):
        """Clean up resources"""
        await self.exit_stack.aclose()

async def main():
    client = MCPClient()
    try:
        await client.connect_to_servers()
        await client.chat_loop()
    finally:
        await client.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
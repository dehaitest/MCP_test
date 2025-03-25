### 1. Clone the Repo

```bash
git clone https://github.com/modelcontextprotocol/servers.git
cd servers
```

### 2. Choose a Server

You can run the example servers using either `npx` or Docker. Each server is located under `src/<server_name>`. For example:

- `filesystem` – a code generation server that interacts with a local file system.

---

`codegen.py` is a code generation agent that reads your requirements and produces runnable code in a local directory.

### Setup

1. Write a configuration file named `server.config`. This file should specify the target directory path where the output files will be written by the agent.

2. Launch the code generation agent:

```bash
python3 codegen.py
```

3. Speak your requirement to the agent in natural language.

Example:

> "Create a FastAPI server with a single GET endpoint that returns 'Hello World'"

The generated code will be saved to the directory specified in your `server.config`.

---

## 🌐 External Tools

Some agents require API keys:

- **Firecrawl (Web Search)**  
  Folder: `src/firecrawlmpc`  
  Get API key: [https://www.firecrawl.dev](https://www.firecrawl.dev)

- **21st.dev (UI Design)**  
  Folder: `src/magicmcp`  
  Get API key: [https://21st.dev](https://21st.dev)

Add your API keys as environment variables or as instructed in each folder's README.

---

## 🧠 Example Projects

These are projects created by the AI code generation agent:

- `nvidia/` – A tech-themed landing page
- `personal_website/` – A developer portfolio site
- `music_player/` – A basic web-based music player

Each folder contains the generated frontend and backend code, ready to deploy or build upon.

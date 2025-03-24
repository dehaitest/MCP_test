document.addEventListener('DOMContentLoaded', () => {
  // Smooth scrolling for anchor links
  document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function(e) {
      e.preventDefault();
      
      const targetId = this.getAttribute('href');
      const targetElement = document.querySelector(targetId);
      
      if (targetElement) {
        window.scrollTo({
          top: targetElement.offsetTop - 100,
          behavior: 'smooth'
        });
      }
    });
  });

  // Fade-in animation for academic work cards
  const academicWorks = document.querySelectorAll('.academic-work');
  
  // Create an intersection observer to detect when elements are in viewport
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        // Add a class when the element is in view
        entry.target.classList.add('visible');
        // Stop observing the element after it's been made visible
        observer.unobserve(entry.target);
      }
    });
  }, {
    root: null, // Use the viewport as the root
    threshold: 0.1, // Trigger when 10% of the element is visible
    rootMargin: '0px 0px -50px 0px' // Adjust this for earlier/later triggering
  });
  
  // Apply initial styles and start observing each academic work
  academicWorks.forEach(work => {
    // Set initial styles (these will be animated in CSS)
    work.style.opacity = '0';
    work.style.transform = 'translateY(20px)';
    // Start observing
    observer.observe(work);
  });

  // Add a CSS class to handle the animation
  const style = document.createElement('style');
  style.textContent = `
    .academic-work.visible {
      opacity: 1 !important;
      transform: translateY(0) !important;
      transition: opacity 0.6s ease, transform 0.6s ease;
    }
  `;
  document.head.appendChild(style);

  // Adding a citation tooltip functionality
  const titles = document.querySelectorAll('.work-header h3');
  
  titles.forEach(title => {
    title.setAttribute('title', 'Click to copy citation');
    title.style.cursor = 'pointer';
    
    title.addEventListener('click', function() {
      // Get the title text and parent work id to identify which citation to copy
      const titleText = this.textContent;
      const workId = this.closest('.academic-work').id;
      let citation = '';
      
      // Generate different citation formats based on work id
      switch(workId) {
        case 'work-1':
          citation = 'Yao, S., Zhao, J., Yu, D., Du, N., Shafran, I., Narasimhan, K., & Cao, Y. (2022). ReAct: Synergizing Reasoning and Acting in Language Models. arXiv:2210.03629.';
          break;
        case 'work-2':
          citation = 'Significant Gravitas. (2023). AutoGPT: An Autonomous GPT-4 Experiment. GitHub Repository, https://github.com/Significant-Gravitas/AutoGPT.';
          break;
        case 'work-3':
          citation = 'Chase, H. (2023). LangChain: Building Applications with LLMs through Composability. arXiv:2310.03722.';
          break;
        default:
          citation = titleText;
      }
      
      // Copy the citation to clipboard
      navigator.clipboard.writeText(citation).then(() => {
        // Create and show a tooltip
        const tooltip = document.createElement('div');
        tooltip.textContent = 'Citation copied!';
        tooltip.style.position = 'absolute';
        tooltip.style.backgroundColor = 'var(--primary-color)';
        tooltip.style.color = 'white';
        tooltip.style.padding = '0.5rem 1rem';
        tooltip.style.borderRadius = 'var(--border-radius)';
        tooltip.style.fontSize = '0.875rem';
        tooltip.style.zIndex = '100';
        tooltip.style.top = `${this.offsetTop - 40}px`;
        tooltip.style.left = `${this.offsetLeft + this.offsetWidth / 2 - 50}px`;
        tooltip.style.opacity = '0';
        tooltip.style.transform = 'translateY(10px)';
        tooltip.style.transition = 'opacity 0.3s, transform 0.3s';
        
        document.body.appendChild(tooltip);
        
        // Animate in
        setTimeout(() => {
          tooltip.style.opacity = '1';
          tooltip.style.transform = 'translateY(0)';
        }, 10);
        
        // Remove after a delay
        setTimeout(() => {
          tooltip.style.opacity = '0';
          tooltip.style.transform = 'translateY(-10px)';
          setTimeout(() => document.body.removeChild(tooltip), 300);
        }, 2000);
      }).catch(err => {
        console.error('Failed to copy: ', err);
      });
    });
  });
}); 
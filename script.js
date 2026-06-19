// Basic JavaScript for the landing page

// Function to handle navigation link clicks
function handleNavClick(event) {
    event.preventDefault();
    const targetId = event.target.getAttribute('href').substring(1);
    const targetSection = document.getElementById(targetId);
    
    if (targetSection) {
        targetSection.scrollIntoView({ behavior: 'smooth' });
    }
}

// Add event listeners to navigation links
document.addEventListener('DOMContentLoaded', function() {
    const navLinks = document.querySelectorAll('nav a');
    navLinks.forEach(link => {
        link.addEventListener('click', handleNavClick);
    });
});
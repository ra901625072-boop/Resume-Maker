window.showToast = function(message, type = 'success') {
  let container = document.querySelector('.toast-container');
  if (!container) {
    container = document.createElement('div');
    container.className = 'toast-container';
    document.body.appendChild(container);
  }
  
  const toast = document.createElement('div');
  const isError = type === 'error' || type === 'danger' || type === 'warning';
  toast.className = `toast ${isError ? 'toast-error' : 'toast-success'}`;
  toast.setAttribute('role', 'alert');
  toast.innerText = message;
  
  container.appendChild(toast);
  
  // Trigger dismiss animation at 3.5s and remove element at 3.8s
  setTimeout(() => {
    toast.classList.add('toast-dismissing');
    setTimeout(() => {
      toast.remove();
      if (container && container.children.length === 0) {
        container.remove();
      }
    }, 300);
  }, 3500);
};

document.addEventListener('DOMContentLoaded', () => {
  // Find any server-rendered flash messages
  const flashMessages = document.querySelectorAll('.flash-messages .alert, .profile-container [style*="background: rgba(99, 102, 241, 0.1)"]');

  if (flashMessages.length > 0) {
    flashMessages.forEach(msg => {
      const text = msg.innerText.trim();
      const isError = msg.classList.contains('alert-error') ||
                      msg.classList.contains('error') ||
                      msg.innerText.toLowerCase().includes('fail') ||
                      msg.innerText.toLowerCase().includes('error');

      window.showToast(text, isError ? 'error' : 'success');
      // Remove original server-rendered flash element to avoid double showing
      msg.remove();
    });
  }
});

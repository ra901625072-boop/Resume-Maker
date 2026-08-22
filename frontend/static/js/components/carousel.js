// carousel.js — Scroll-based dot sync for template carousel
(function() {
  const carousel = document.querySelector('.carousel');
  const track = document.getElementById('templateTrack');
  const dots = document.querySelectorAll('.carousel-dots .dot');
  if (!carousel || !track || !dots.length) return;

  const cards = track.querySelectorAll('.template-card');

  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting && entry.intersectionRatio >= 0.5) {
        const index = Array.from(cards).indexOf(entry.target);
        if (index !== -1) {
          dots.forEach((dot, i) => dot.classList.toggle('active', i === index));
        }
      }
    });
  }, {
    root: carousel,   // <-- scrollable container, not the track
    threshold: 0.5
  });

  cards.forEach(card => observer.observe(card));

  // Dot click: scroll card into view within the carousel container
  dots.forEach(dot => {
    dot.addEventListener('click', () => {
      const index = parseInt(dot.dataset.index, 10);
      const target = cards[index];
      if (target) {
        target.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' });
      }
    });
  });
})();

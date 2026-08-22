document.addEventListener('DOMContentLoaded', () => {
    const scrollShell = document.querySelector('.template-scroll');
    const track = document.getElementById('template-track');

    if (!scrollShell || !track) {
        return;
    }

    let offsetY = 0;
    let speed = 0.4;
    let manualBoost = 0;

    const animate = () => {
        offsetY -= speed + manualBoost;

        if (Math.abs(offsetY) >= track.scrollHeight / 2) {
            offsetY = 0;
        }

        track.style.transform = `translateY(${offsetY}px)`;
        manualBoost *= 0.9;
        window.requestAnimationFrame(animate);
    };

    animate();

    scrollShell.addEventListener('wheel', (event) => {
        event.preventDefault();
        manualBoost = event.deltaY * 0.08;
    }, { passive: false });
});

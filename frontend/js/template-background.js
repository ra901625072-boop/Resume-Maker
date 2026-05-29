document.addEventListener('DOMContentLoaded', () => {
    const body = document.body;
    const downloadButton = document.querySelector('[data-download-format="pdf"]');

    const toggleShellControls = (hidden) => {
        document.querySelectorAll('[data-shell-control]').forEach((element) => {
            element.style.display = hidden ? 'none' : '';
        });
    };

    const generatePDF = () => {
        const element =
            document.querySelector('[data-resume-root]') ||
            document.querySelector('.page, .wrap, .container, .resume');

        if (!element || typeof html2pdf === 'undefined') {
            return;
        }

        const filename = body.dataset.pdfFilename || 'resume.pdf';

        toggleShellControls(true);

        html2pdf().set({
            margin: 0,
            filename,
            image: { type: 'jpeg', quality: 0.98 },
            html2canvas: { scale: 2, useCORS: true, letterRendering: true },
            jsPDF: { unit: 'mm', format: 'a4', orientation: 'portrait' }
        }).from(element).save().finally(() => {
            toggleShellControls(false);
        });
    };

    if (downloadButton) {
        downloadButton.addEventListener('click', generatePDF);
    }

    window.generatePDF = generatePDF;

    if (window.location.search.includes('print=true')) {
        window.setTimeout(() => window.print());
    }

    if (body.dataset.printMode === 'true') {
        window.addEventListener('load', () => {
            window.setTimeout(generatePDF, 1500);
        });
    }
});

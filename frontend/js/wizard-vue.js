const { createApp } = Vue;

createApp({
    data() {
        return {
            currentStep: 1,
            totalSteps: 4,
            isSaving: false,
            isImporting: false,
            errors: {},
            formData: {
                resume_id: '',
                template: '',
                name: '',
                title: '',
                email: '',
                phone: '',
                address: '',
                summary: '',
                skills: '',
                languages: [{ value: '' }],
                experience: [
                    { id: '', title: '', company: '', duration: '', description: '', isGenerating: false }
                ],
                education: [
                    { id: '', degree: '', university: '', year: '' }
                ]
            },
            photoFile: null,
            photoPreviewUrl: '',
            isGeneratingSummary: false
        };
    },
    mounted() {
        // Priority 1: Pre-loaded data injected via Jinja (edit mode / session import)
        if (window.INITIAL_RESUME_DATA) {
            this.populateData(window.INITIAL_RESUME_DATA);
            return;
        }
        // Priority 2: Data saved by the AI JSON Extractor page via localStorage
        try {
            const stored = localStorage.getItem('import_resume_data');
            if (stored) {
                const parsed = JSON.parse(stored);
                localStorage.removeItem('import_resume_data');
                this.populateData(parsed);
                if (window.showToast) window.showToast('Resume data loaded from AI Extractor! 🎉', 'success');
            }
        } catch (e) {
            // Silently ignore stale / malformed localStorage entries
        }
    },
    methods: {
        changeStep(n) {
            if (n === 1 && !this.validateCurrentStep()) {
                return;
            }

            const next = this.currentStep + n;
            if (next >= 1 && next <= this.totalSteps) {
                this.currentStep = next;
                this.scrollToTop();
            }
        },
        scrollToTop() {
            const container = document.querySelector('.form-container');
            if (container) {
                const headerHeight = document.querySelector('.app-header')?.offsetHeight || 72;
                const topOffset = container.getBoundingClientRect().top + window.pageYOffset - headerHeight - 20;
                window.scrollTo({ top: topOffset, behavior: 'smooth' });
            }
        },
        validateCurrentStep() {
            this.errors = {};
            let isValid = true;

            if (this.currentStep === 1) {
                if (!this.formData.name) this.errors.name = true;
                if (!this.formData.title) this.errors.title = true;
                if (!this.formData.email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(this.formData.email)) this.errors.email = true;
                if (!this.formData.phone || !/^[\d\s\-–\/]+$/.test(this.formData.phone)) this.errors.phone = true;
                if (!this.formData.address) this.errors.address = true;
            } else if (this.currentStep === 2) {
                // Check if filled items are valid
                this.formData.experience.forEach((exp, idx) => {
                    if (exp.title || exp.company) {
                        if (!exp.title) this.errors[`exp_${idx}_title`] = true;
                        if (!exp.company) this.errors[`exp_${idx}_company`] = true;
                    }
                });
            } else if (this.currentStep === 4) {
                if (!this.formData.template) {
                    this.errors.template = true;
                    isValid = false;
                }
            }

            if (Object.keys(this.errors).length > 0) {
                isValid = false;
                if (window.showToast) window.showToast('Please fix the errors before proceeding.', 'error');
            }
            return isValid;
        },
        addExperience() {
            this.formData.experience.push({ id: '', title: '', company: '', duration: '', description: '', isGenerating: false });
        },
        removeExperience(index) {
            this.formData.experience.splice(index, 1);
        },
        addEducation() {
            this.formData.education.push({ id: '', degree: '', university: '', year: '' });
        },
        removeEducation(index) {
            this.formData.education.splice(index, 1);
        },
        addLanguage() {
            this.formData.languages.push({ value: '' });
        },
        removeLanguage(index) {
            this.formData.languages.splice(index, 1);
        },
        handlePhotoUpload(event) {
            const file = event.target.files[0];
            if (file) {
                this.photoFile = file;
                const reader = new FileReader();
                reader.onload = (e) => {
                    this.photoPreviewUrl = e.target.result;
                };
                reader.readAsDataURL(file);
            }
        },
        async handleJsonImport(event) {
            const file = event.target.files[0];
            if (!file) return;

            this.isImporting = true;
            try {
                const text = await file.text();
                const data = JSON.parse(text);
                this.populateData(data);
                if (window.showToast) window.showToast('Data imported successfully!', 'success');
            } catch (err) {
                if (window.showToast) window.showToast('Invalid JSON file.', 'error');
            } finally {
                this.isImporting = false;
                event.target.value = '';
            }
        },
        // ── Schema-agnostic data normalizer ────────────────────────────────────
        // Accepts three formats and maps them to the wizard's flat formData:
        //   1. Legacy flat JSON  { name, title, email, ... }
        //   2. Optimized nested  { personal_info: {…}, professional_summary, … }
        //   3. AI Analyzer       { candidate: { contact:{…} }, structured_data:{…}, … }
        //   4. AI Extract output { structured_data: { name, title, … } }
        populateData(data) {
            if (!data || typeof data !== 'object') return;

            // ── Step 1: Unwrap AI extraction envelope if present ───────────────
            // Format: { raw_text, structured_data: {…}, metadata: {…} }
            if (data.structured_data && typeof data.structured_data === 'object') {
                data = { ...data.structured_data, template: data.template || data.selected_template || '' };
            }

            // ── Step 2: Normalize to a flat intermediate object ───────────────
            const norm = {};

            // --- Personal Info ---
            // Optimized: { personal_info: { full_name, job_title, email, phone, address } }
            if (data.personal_info && typeof data.personal_info === 'object') {
                const pi = data.personal_info;
                norm.name    = pi.full_name    || pi.name    || '';
                norm.title   = pi.job_title    || pi.title   || '';
                norm.email   = pi.email        || '';
                norm.phone   = pi.phone        || '';
                norm.address = pi.address      || '';
                norm.photo   = pi.photo_url    || pi.photo   || '';
            }
            // AI Analyzer: { candidate: { name, role, contact: { email, phone, address } } }
            else if (data.candidate && typeof data.candidate === 'object') {
                const c = data.candidate;
                norm.name    = c.name  || c.full_name || '';
                norm.title   = c.role  || c.job_title || c.title || '';
                const contact = c.contact || {};
                norm.email   = contact.email   || data.email   || '';
                norm.phone   = contact.phone   || data.phone   || '';
                norm.address = contact.address || data.address || '';
            }
            // Legacy flat: { name, title, email, phone, address }
            else {
                norm.name    = data.name    || data.full_name    || '';
                norm.title   = data.title   || data.job_title    || '';
                norm.email   = data.email   || '';
                norm.phone   = data.phone   || '';
                norm.address = data.address || '';
                norm.photo   = data.photo   || data.photo_url   || '';
            }

            // --- Professional Summary ---
            norm.summary = data.professional_summary || data.summary || '';

            // --- Skills ---
            // Could be a comma-string "Python, Flask" or an array ["Python","Flask"]
            const rawSkills = data.skills || [];
            if (Array.isArray(rawSkills)) {
                norm.skills = rawSkills.join(', ');
            } else {
                norm.skills = String(rawSkills);
            }

            // --- Template ---
            norm.template = data.selected_template || data.template || '';

            // --- Resume ID (edit mode) ---
            norm.id = data.id || data.resume_id || '';

            // ── Step 3: Populate formData ─────────────────────────────────────
            if (norm.id)      this.formData.resume_id = norm.id;
            if (norm.template) this.formData.template = norm.template;
            if (norm.name)    this.formData.name    = norm.name;
            if (norm.title)   this.formData.title   = norm.title;
            if (norm.email)   this.formData.email   = norm.email;
            if (norm.phone)   this.formData.phone   = norm.phone;
            if (norm.address) this.formData.address = norm.address;
            if (norm.summary) this.formData.summary = norm.summary;
            if (norm.skills)  this.formData.skills  = norm.skills;

            // ── Languages ─────────────────────────────────────────────────────
            // Supported: ["English (Native)"] | [{ value: "…" }] | [{ language, level }]
            const rawLangs = data.languages || [];
            if (Array.isArray(rawLangs) && rawLangs.length > 0) {
                this.formData.languages = rawLangs.map(l => {
                    if (typeof l === 'string')       return { value: l };
                    if (l.value)                     return { value: l.value };
                    if (l.language) {
                        const lvl = l.level ? ` (${l.level})` : '';
                        return { value: l.language + lvl };
                    }
                    return { value: String(l) };
                }).filter(l => l.value.trim() !== '');
            }

            // ── Experience ────────────────────────────────────────────────────
            // Supported: { title|job_title, company|company_name, duration, description|start_date+end_date }
            const rawExp = data.experience || [];
            if (Array.isArray(rawExp) && rawExp.length > 0) {
                this.formData.experience = rawExp.map(e => {
                    const dur = e.duration ||
                        ((e.start_date || '') + (e.end_date ? ' – ' + e.end_date : ''));
                    const desc = Array.isArray(e.description)
                        ? e.description.join('\n')
                        : (e.description || '');
                    return {
                        id:           e.id || '',
                        title:        e.title       || e.job_title    || '',
                        company:      e.company     || e.company_name || '',
                        duration:     dur.trim(),
                        description:  desc,
                        isGenerating: false
                    };
                }).filter(e => e.title.trim() !== '');
                if (this.formData.experience.length === 0) {
                    this.formData.experience = [{ id: '', title: '', company: '', duration: '', description: '', isGenerating: false }];
                }
            }

            // ── Education ─────────────────────────────────────────────────────
            // Supported: { degree, university|institution, year }
            const rawEdu = data.education || [];
            if (Array.isArray(rawEdu) && rawEdu.length > 0) {
                this.formData.education = rawEdu.map(e => ({
                    id:         e.id         || '',
                    degree:     e.degree     || '',
                    university: e.university || e.institution || '',
                    year:       e.year       || ''
                })).filter(e => e.degree.trim() !== '');
                if (this.formData.education.length === 0) {
                    this.formData.education = [{ id: '', degree: '', university: '', year: '' }];
                }
            }
        },
        async generateSummary() {
            if (!this.formData.title) {
                if (window.showToast) window.showToast('Please provide a Job Title first.', 'warning');
                return;
            }

            this.isGeneratingSummary = true;
            try {
                const csrfToken = document.querySelector('input[name="csrf_token"]').value;
                const res = await fetch('/api/generate-summary', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
                    body: JSON.stringify({
                        name: this.formData.name,
                        title: this.formData.title,
                        skills: this.formData.skills
                    })
                });
                const data = await res.json();
                if (data.success) {
                    this.formData.summary = data.data;
                    if (window.showToast) window.showToast('Summary generated!', 'success');
                } else {
                    if (window.showToast) window.showToast(data.error || 'Failed to generate', 'error');
                }
            } catch (err) {
                if (window.showToast) window.showToast('Network error.', 'error');
            } finally {
                this.isGeneratingSummary = false;
            }
        },
        async generateExperience(index) {
            const exp = this.formData.experience[index];
            if (!exp.title) {
                if (window.showToast) window.showToast('Please provide a Job Title for this experience.', 'warning');
                return;
            }

            exp.isGenerating = true;
            try {
                const csrfToken = document.querySelector('input[name="csrf_token"]').value;
                const res = await fetch('/api/generate-experience', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
                    body: JSON.stringify({
                        title: exp.title,
                        company: exp.company,
                        duration: exp.duration,
                        skills: this.formData.skills
                    })
                });
                const data = await res.json();
                if (data.success) {
                    exp.description = data.data;
                    if (window.showToast) window.showToast('Experience generated!', 'success');
                } else {
                    if (window.showToast) window.showToast(data.error || 'Failed to generate', 'error');
                }
            } catch (err) {
                if (window.showToast) window.showToast('Network error.', 'error');
            } finally {
                exp.isGenerating = false;
            }
        },
        async submitForm() {
            if (this.currentStep !== this.totalSteps) {
                this.changeStep(1);
                return;
            }
            if (!this.validateCurrentStep()) return;

            this.isSaving = true;
            try {
                const csrfToken = document.querySelector('input[name="csrf_token"]').value;
                let photoUrl = '';

                // Upload photo first if exists
                if (this.photoFile) {
                    const fd = new FormData();
                    fd.append('photo', this.photoFile);
                    const photoRes = await fetch('/upload-photo', {
                        method: 'POST',
                        headers: { 'X-CSRFToken': csrfToken },
                        body: fd
                    });
                    const photoData = await photoRes.json();
                    if (photoData.success) {
                        photoUrl = photoData.url;
                    } else {
                        throw new Error(photoData.error || 'Photo upload failed');
                    }
                }

                // Build JSON Payload
                const rawSkillsStr = Array.isArray(this.formData.skills)
                    ? this.formData.skills.join(', ')
                    : (this.formData.skills || '');
                const payload = {
                    ...this.formData,
                    languages: this.formData.languages.map(l => l.value).filter(v => v.trim() !== ''),
                    skills: rawSkillsStr.split(',').map(s => s.trim()).filter(s => s)
                };

                if (photoUrl) payload.photo = photoUrl;

                // Clean up vue-specific flags
                payload.experience = payload.experience.map(({ isGenerating, ...rest }) => rest).filter(e => e.title.trim() !== '');
                payload.education = payload.education.filter(e => e.degree.trim() !== '');

                // Async JSON API
                const res = await fetch('/generate', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': csrfToken
                    },
                    body: JSON.stringify(payload)
                });

                const result = await res.json();
                if (result.success) {
                    window.location.href = result.redirect;
                } else {
                    throw new Error(result.error || 'Failed to save');
                }

            } catch (err) {
                if (window.showToast) window.showToast(err.message || 'An error occurred.', 'error');
                this.isSaving = false;
            }
        }
    }
}).mount('#vueApp');

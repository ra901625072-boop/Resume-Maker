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
            isGeneratingSummary: false,
            isEditing: false
        };
    },
    async mounted() {
        // Priority 1: Check for edit query param (for static Vercel frontend)
        const urlParams = new URLSearchParams(window.location.search);
        const resumeId = urlParams.get('id');
        if (resumeId) {
            this.isEditing = true;
            this.formData.resume_id = resumeId;
            try {
                const res = await window.apiFetch(`/api/resumes/${resumeId}`);
                if (res.ok) {
                    const data = await res.json();
                    if (data.success && data.data) {
                        this.populateData(data.data);
                        if (data.data.photo_url) {
                            const pUrl = data.data.photo_url;
                            if (pUrl.startsWith('http')) {
                                this.photoPreviewUrl = pUrl;
                            } else {
                                const cleanUrl = pUrl.startsWith('/') ? pUrl.slice(1) : pUrl;
                                this.photoPreviewUrl = (window.API_BASE_URL || '') + '/' + cleanUrl;
                            }
                        }
                        if (window.showToast) window.showToast('Resume loaded for editing! 📝', 'success');
                    }
                }
            } catch (err) {
                console.error('Error loading resume details:', err);
            }
            return;
        }

        // Priority 2: Pre-loaded data injected via Jinja (edit mode / session import)
        if (window.INITIAL_RESUME_DATA) {
            this.populateData(window.INITIAL_RESUME_DATA);
            return;
        }
        // Priority 3: Data saved by the AI JSON Extractor page via localStorage
        try {
            const stored = localStorage.getItem('import_resume_data');
            if (stored) {
                const parsed = JSON.parse(stored);
                localStorage.removeItem('import_resume_data');
                this.populateData(parsed);
                if (window.showToast) window.showToast('Resume data loaded from AI Extractor! 🎉', 'success');
                return;
            }
        } catch (e) {
            // Silently ignore stale / malformed localStorage entries
        }

        // Priority 4: Authenticated user profile auto-fill for new resumes
        if (window.AuthGuard && typeof window.AuthGuard.getUser === 'function') {
            const user = window.AuthGuard.getUser();
            if (user) {
                if (!this.formData.name && user.name) {
                    this.formData.name = user.name;
                }
                if (!this.formData.email && user.email) {
                    this.formData.email = user.email;
                }
                if (!this.formData.template && user.settings && user.settings.default_template) {
                    this.formData.template = user.settings.default_template;
                }
            }
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
        // ── Flexible Data Normalizer ──────────────────────────────────────────
        // Accepts:
        //   1. 4-Tier Schema     { candidate: { personal_information, work_experience, skills, ... } }
        //   2. AI Extract output { structured_data: { name, title, … } }
        //   3. AI Analyzer       { candidate: { contact:{…} }, structured_data:{…}, … }
        //   4. Legacy flat JSON  { name, title, email, ... }
        populateData(data) {
            if (!data || typeof data !== 'object') return;

            // ── Step 1: Handle Candidate from 4-Tier Schema ───────────────────
            const cand = data.candidate || (data.resume && data.resume.candidate) || null;
            const sd = data.structured_data || null;

            const norm = {};

            // --- Personal Info ---
            if (cand && cand.personal_information && typeof cand.personal_information === 'object') {
                const pi = cand.personal_information;
                norm.name    = pi.full_name || pi.name || '';
                norm.title   = pi.job_title || pi.title || '';
                norm.email   = pi.email || '';
                norm.phone   = pi.phone || '';
                if (pi.location && typeof pi.location === 'object') {
                    const loc = [pi.location.city, pi.location.state, pi.location.country].filter(Boolean).join(', ');
                    norm.address = loc || pi.address || '';
                } else {
                    norm.address = pi.address || '';
                }
                norm.photo   = pi.photo_url || pi.photo || '';
                norm.summary = cand.professional_summary || cand.career_objective || cand.summary || '';
            } else if (data.personal_info && typeof data.personal_info === 'object') {
                const pi = data.personal_info;
                norm.name    = pi.full_name    || pi.name    || '';
                norm.title   = pi.job_title    || pi.title   || '';
                norm.email   = pi.email        || '';
                norm.phone   = pi.phone        || '';
                norm.address = pi.address      || '';
                norm.photo   = pi.photo_url    || pi.photo   || '';
                norm.summary = data.professional_summary || data.summary || '';
            } else if (sd && typeof sd === 'object') {
                norm.name    = sd.name || sd.full_name || '';
                norm.title   = sd.title || sd.job_title || '';
                norm.email   = sd.email || '';
                norm.phone   = sd.phone || '';
                norm.address = sd.address || '';
                norm.photo   = sd.photo || sd.photo_url || '';
                norm.summary = sd.professional_summary || sd.summary || '';
            } else {
                norm.name    = data.name    || data.full_name    || '';
                norm.title   = data.title   || data.job_title    || '';
                norm.email   = data.email   || '';
                norm.phone   = data.phone   || '';
                norm.address = data.address || '';
                norm.photo   = data.photo   || data.photo_url   || '';
                norm.summary = data.professional_summary || data.summary || '';
            }

            // --- Skills ---
            const rawSkills = (cand && cand.skills) || (sd && sd.skills) || data.skills || [];
            if (rawSkills && typeof rawSkills === 'object' && !Array.isArray(rawSkills)) {
                const allS = [];
                Object.values(rawSkills).forEach(val => {
                    if (Array.isArray(val)) allS.push(...val);
                    else if (typeof val === 'string' && val.trim()) allS.push(val);
                });
                norm.skills = [...new Set(allS)].join(', ');
            } else if (Array.isArray(rawSkills)) {
                norm.skills = rawSkills.join(', ');
            } else {
                norm.skills = String(rawSkills || '');
            }

            // --- Template & Resume ID ---
            norm.template = data.selected_template || data.template || '';
            norm.id = data.id || data.resume_id || '';

            // ── Step 2: Populate Basic Fields ─────────────────────────────────
            if (norm.id)       this.formData.resume_id = norm.id;
            if (norm.template) this.formData.template  = norm.template;
            if (norm.name)     this.formData.name      = norm.name;
            if (norm.title)    this.formData.title     = norm.title;
            if (norm.email)    this.formData.email     = norm.email;
            if (norm.phone)    this.formData.phone     = norm.phone;
            if (norm.address)  this.formData.address   = norm.address;
            if (norm.summary)  this.formData.summary   = norm.summary;
            if (norm.skills)   this.formData.skills    = norm.skills;

            // ── Languages ─────────────────────────────────────────────────────
            const rawLangs = (cand && cand.languages) || (sd && sd.languages) || data.languages || [];
            if (Array.isArray(rawLangs) && rawLangs.length > 0) {
                this.formData.languages = rawLangs.map(l => {
                    if (typeof l === 'string') return { value: l };
                    if (l.value) return { value: l.value };
                    if (l.language) {
                        const lvl = l.proficiency || l.level ? ` (${l.proficiency || l.level})` : '';
                        return { value: l.language + lvl };
                    }
                    return { value: String(l) };
                }).filter(l => l.value.trim() !== '');
            }

            // ── Experience ────────────────────────────────────────────────────
            const rawExp = (cand && (cand.work_experience || cand.experience)) || (sd && sd.experience) || data.experience || data.work_experience || [];
            if (Array.isArray(rawExp) && rawExp.length > 0) {
                this.formData.experience = rawExp.map(e => {
                    const dur = e.duration ||
                        [e.start_date, e.end_date || (e.is_current ? 'Present' : '')].filter(Boolean).join(' – ');
                    let desc = e.description || '';
                    if (!desc && Array.isArray(e.responsibilities) && e.responsibilities.length > 0) {
                        desc = e.responsibilities.map(r => `• ${r}`).join('\n');
                    }
                    return {
                        id:           e.id || '',
                        title:        e.title || e.job_title || '',
                        company:      e.company || e.company_name || '',
                        duration:     dur.trim(),
                        description:  desc,
                        isGenerating: false
                    };
                }).filter(e => e.title.trim() !== '' || e.company.trim() !== '');
                if (this.formData.experience.length === 0) {
                    this.formData.experience = [{ id: '', title: '', company: '', duration: '', description: '', isGenerating: false }];
                }
            }

            // ── Education ─────────────────────────────────────────────────────
            const rawEdu = (cand && cand.education) || (sd && sd.education) || data.education || [];
            if (Array.isArray(rawEdu) && rawEdu.length > 0) {
                this.formData.education = rawEdu.map(e => {
                    const deg = e.degree ? (e.field_of_study ? `${e.degree} in ${e.field_of_study}` : e.degree) : (e.field_of_study || '');
                    const yr = e.year || [e.start_date, e.end_date].filter(Boolean).join(' – ');
                    return {
                        id:         e.id || '',
                        degree:     deg,
                        university: e.university || e.institution || e.school || '',
                        year:       yr
                    };
                }).filter(e => e.degree.trim() !== '' || e.university.trim() !== '');
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
                const res = await window.apiFetch('/api/generate-summary', {
                    method: 'POST',
                    body: {
                        name: this.formData.name,
                        title: this.formData.title,
                        skills: this.formData.skills
                    }
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
                const res = await window.apiFetch('/api/generate-experience', {
                    method: 'POST',
                    body: {
                        title: exp.title,
                        company: exp.company,
                        duration: exp.duration,
                        skills: this.formData.skills
                    }
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
                let photoUrl = '';

                // Upload photo first if exists
                if (this.photoFile) {
                    const fd = new FormData();
                    fd.append('photo', this.photoFile);

                    const photoRes = await window.apiFetch('/upload-photo', {
                        method: 'POST',
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
                const res = await window.apiFetch('/generate', {
                    method: 'POST',
                    body: payload
                });

                const result = await res.json();
                if (result.success) {
                    window.location.href = `/resume?id=${result.resume_id}`;
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

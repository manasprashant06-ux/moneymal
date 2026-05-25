import axios from 'axios';

const API = axios.create({
    baseURL: 'http://localhost:8000/api',
    timeout: 30000,  // Short timeout — each call is just a small HTTP ping
});

/**
 * analyzeFile — Async Job Pattern (No Timeout)
 * 1. Submits the CSV → gets a job_id immediately
 * 2. Polls /api/result/{job_id} every 3 seconds until done
 * 3. Returns the full result once complete
 */
export async function analyzeFile(file, onProgress) {
    // Step 1: Submit file and get job_id
    const form = new FormData();
    form.append('file', file);

    let jobId;
    try {
        const submitRes = await API.post('/analyze', form, {
            headers: { 'Content-Type': 'multipart/form-data' },
            onUploadProgress: (e) => {
                if (onProgress && e.total) {
                    onProgress(Math.round((e.loaded / e.total) * 20));
                }
            },
        });
        jobId = submitRes.data.job_id;
    } catch (err) {
        throw new Error('Failed to submit file: ' + (err?.response?.data?.detail || err.message));
    }

    // Step 2: Poll until done
    let attempts = 0;
    const MAX_ATTEMPTS = 300;  // 300 × 3s = 15 minutes max wait

    while (attempts < MAX_ATTEMPTS) {
        await new Promise(r => setTimeout(r, 3000));  // wait 3 seconds between polls
        attempts++;

        try {
            const pollRes = await API.get(`/result/${jobId}`);
            const job = pollRes.data;

            if (job.status === 'done') {
                if (onProgress) onProgress(100);
                return { result: job.result, graph: job.graph };
            }

            if (job.status === 'error') {
                throw new Error('Engine error: ' + (job.detail || 'Unknown error'));
            }

            // Still running — update progress (20% → 95% during processing)
            if (onProgress) {
                const progress = Math.min(95, 20 + Math.round((attempts / MAX_ATTEMPTS) * 75));
                onProgress(progress);
            }
        } catch (pollErr) {
            // Ignore transient poll errors, keep retrying
            if (pollErr.message.startsWith('Engine error')) throw pollErr;
        }
    }

    throw new Error('Analysis timed out after 15 minutes.');
}

export async function checkHealth() {
    const res = await API.get('/health');
    return res.data;
}

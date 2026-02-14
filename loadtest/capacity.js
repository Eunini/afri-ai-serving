import http from 'k6/http';
import { check } from 'k6';

const mode = __ENV.MODE || 'chat';
const audio = mode === 'speech' ? open(__ENV.AUDIO_FILE, 'b') : null;
const scenarios = {};
for (const [index, rate] of [1, 2, 5].entries()) {
  scenarios[`steady_${rate}_per_10s`] = {
    executor: 'constant-arrival-rate', rate, timeUnit: '10s',
    startTime: `${index * 2}m`, duration: '2m', gracefulStop: '30s',
    preAllocatedVUs: 4, maxVUs: 16, tags: { offered_rps: String(rate / 10) },
  };
}
export const options = { scenarios, thresholds: { http_req_failed: ['rate<0.05'] } };
export default function () {
  const headers = { Authorization: `Bearer ${__ENV.API_KEY}` };
  headers['Content-Type'] = mode === 'speech' ? 'audio/wav' : 'application/json';
  const body = mode === 'speech' ? audio : JSON.stringify({
    model: 'local', messages: [{role: 'user', content: 'Explain photosynthesis in two sentences.'}],
    max_tokens: 64, temperature: 0, stream: false,
  });
  const response = http.post(
    `${__ENV.BASE_URL}${mode === 'speech' ? '/transcribe' : '/v1/chat/completions'}`,
    body, { headers, timeout: '180s' },
  );
  check(response, { 'inference succeeds': r => r.status === 200 });
}

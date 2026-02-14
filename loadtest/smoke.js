import http from 'k6/http';
import { check } from 'k6';
import { sha256 } from 'k6/crypto';

const mode = __ENV.MODE || 'chat';
const audio = mode === 'speech' ? open(__ENV.AUDIO_FILE, 'b') : null;
export const options = { vus: 1, iterations: 1, thresholds: { checks: ['rate==1'] } };
export default function () {
  const headers = { Authorization: `Bearer ${__ENV.API_KEY}` };
  headers['Content-Type'] = mode === 'speech' ? 'audio/wav' : 'application/json';
  const body = mode === 'speech' ? audio : JSON.stringify({
    model: 'local', messages: [{ role: 'user', content: 'Reply with the word ready.' }],
    max_tokens: 8, temperature: 0, stream: false,
  });
  const response = http.post(
    `${__ENV.BASE_URL}${mode === 'speech' ? '/transcribe' : '/v1/chat/completions'}`,
    body, { headers, timeout: '180s' },
  );
  check(response, { 'real inference succeeds through TLS ingress': r => r.status === 200 });
  console.log(JSON.stringify({ mode, status: response.status, milliseconds: response.timings.duration,
    response_sha256: sha256(response.body, 'hex') }));
}

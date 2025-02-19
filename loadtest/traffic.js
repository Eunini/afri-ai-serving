import http from 'k6/http';
import { check } from 'k6';
import { Trend, Rate } from 'k6/metrics';

const latency = new Trend('inference_latency_ms', true);
const errors = new Rate('inference_errors');
const mode = __ENV.MODE || 'chat';
const audio = mode === 'speech' ? open(__ENV.AUDIO_FILE, 'b') : null;
export const options = {
  scenarios: {
    staircase: {
      executor: 'ramping-arrival-rate', startRate: 1, timeUnit: '1s',
      preAllocatedVUs: 4, maxVUs: 64,
      stages: [
        {target: 1, duration: '2m'}, {target: 2, duration: '2m'},
        {target: 4, duration: '2m'}, {target: 8, duration: '2m'},
        {target: 0, duration: '3m'},
      ],
    },
  },
  thresholds: {http_req_failed: ['rate<0.05'], inference_latency_ms: ['p(95)<30000']},
};
export default function () {
  const headers = {Authorization: `Bearer ${__ENV.API_KEY}`};
  let response;
  if (mode === 'speech') {
    headers['Content-Type'] = 'audio/wav';
    response = http.post(`${__ENV.BASE_URL}/transcribe`, audio, {headers, timeout: '180s'});
  } else {
    headers['Content-Type'] = 'application/json';
    response = http.post(`${__ENV.BASE_URL}/v1/chat/completions`, JSON.stringify({
      model: 'local', messages: [{role: 'user', content: 'Explain photosynthesis in two sentences.'}],
      max_tokens: 64, temperature: 0, stream: false,
    }), {headers, timeout: '180s'});
  }
  const good = check(response, {'inference succeeds': r => r.status === 200});
  latency.add(response.timings.duration, {mode});
  errors.add(!good, {mode});
}

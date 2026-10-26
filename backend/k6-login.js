// FastAPI 登录压测：查询数据库并使用 Argon2 验证密码。
// 运行前执行 Python seed，确认 admin 账号可登录。
// 注意：只压 /healthz 和 /login，绝对不要压 /chat/stream（烧钱 + 上游限流 + 熔断打开）。
import http from 'k6/http';
import { check } from 'k6';

export const options = {
  scenarios: {
    login: {
      executor: 'constant-arrival-rate',
      rate: 50, timeUnit: '1s', // 每秒固定到达 50 次登录
      duration: '30s',
      preAllocatedVUs: 100,
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<500'], // 登录含 Argon2，P95 阈值放宽到 500ms
  },
};

export default function () {
  const res = http.post(`${__ENV.BASE || 'http://localhost:8080'}/api/v1/auth/login`,
    JSON.stringify({ username: 'admin', password: 'admin123' }),
    { headers: { 'Content-Type': 'application/json' } });
  check(res, { 'status 200': (r) => r.status === 200 });
}

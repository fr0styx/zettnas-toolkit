import { describe, it, expect } from 'vitest';
import { lintCompose } from '../compose-lint.js';

describe('compose lint (AI-22)', () => {
  it('flags host-level access', () => {
    const yaml = `services:
  app:
    image: x
    privileged: true
    network_mode: host
    cap_add:
      - SYS_ADMIN
    security_opt:
      - apparmor:unconfined
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /:/host
      - /etc:/hostetc:ro
      - ./data:/data
`;
    const f = lintCompose(yaml);
    const lines = f.map((x) => x.line);
    expect(lines).toEqual(expect.arrayContaining([4, 5, 7, 9, 11, 12, 13]));
    expect(lines).not.toContain(14);
    expect(f.filter((x) => x.level === 'danger').length).toBeGreaterThanOrEqual(5);
  });

  it('is quiet for an ordinary stack and ignores comments', () => {
    const yaml = `services:
  web:
    image: nginx:1.27
    # privileged: true
    ports:
      - "8080:80"
    volumes:
      - ./html:/usr/share/nginx/html:ro
`;
    expect(lintCompose(yaml)).toEqual([]);
  });
});

import { defineConfig } from 'vitest/config';

// Node environment, and only the pure domain. No TestBed, no Karma, no headless
// Chrome: this code never touches the DOM, and a browser runner would add ~10s of
// startup to catch nothing. Rejecting the framework default is the point.
export default defineConfig({
  test: {
    environment: 'node',
    include: ['src/app/domain/**/*.spec.ts'],
  },
});

FROM mcr.microsoft.com/playwright:v1.62.1-noble

WORKDIR /opt/browser-tests

RUN npm install -g pnpm@11.23.0

COPY package.json pnpm-lock.yaml ./
RUN pnpm --pm-on-fail=ignore install --frozen-lockfile

ENV NODE_PATH=/opt/browser-tests/node_modules

CMD ["/opt/browser-tests/node_modules/.bin/playwright", "test", "--config", "/repo/tests/browser/playwright.config.js"]

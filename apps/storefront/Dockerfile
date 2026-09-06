# Ticket 07 (real-estate): a real, resolvable, deliberately old npm
# dependency tree (Angular 9, early 2020) -- this stage genuinely installs
# it, proving the tree is real and not just a fixture Renovate/the
# vulnerability scanner would never actually see resolve. The served
# content itself is a hand-written static page (no `ng build` -- the point
# of this app is the dependency staleness signal, not a compiled Angular
# bundle) so the deploy stays fast and small.
FROM node:18-alpine AS deps
WORKDIR /app
COPY package.json ./
RUN npm install --legacy-peer-deps --no-audit --no-fund

FROM nginx:1.27-alpine
COPY public/index.html /usr/share/nginx/html/index.html
# The dependency tree's evidence lives outside the nginx docroot (not
# publicly served) but still in the shipped image. Ships the real
# node_modules too, not just the lockfile: trivy-operator's image-mode
# scan only runs its node-pkg analyzer (reads each dependency's own
# node_modules/*/package.json), not the npm lockfile analyzer -- found
# live comparing `trivy image` against `trivy fs` on the identical
# lockfile (image mode reported only this project's own name/version;
# fs mode correctly parsed the full Angular/rxjs tree from the lockfile
# alone). A real image-size-vs-scanner-visibility tradeoff, deliberately
# taken here since the whole point of this app is that visibility.
COPY --from=deps /app/package.json /app/package-lock.json /app/node_modules /opt/app-deps/
EXPOSE 80

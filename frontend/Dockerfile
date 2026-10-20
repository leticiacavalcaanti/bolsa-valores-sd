FROM node:22-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
# As URLs são embutidas no bundle: o navegador do jogador é quem chama as APIs.
ARG NEXT_PUBLIC_AUTH_URL=http://localhost:8001
ARG NEXT_PUBLIC_MARKET_URL=http://localhost:8002
ENV NEXT_PUBLIC_AUTH_URL=$NEXT_PUBLIC_AUTH_URL
ENV NEXT_PUBLIC_MARKET_URL=$NEXT_PUBLIC_MARKET_URL
RUN npm run build
CMD ["npm", "start"]

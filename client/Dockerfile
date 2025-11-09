# Use Node 22 (LTS) for building and running Next.js
FROM node:22-alpine AS builder

WORKDIR /app

# Copy dependency files and install
COPY package*.json ./
RUN npm install

# Copy all source files
COPY . .

# Build the Next.js app
RUN npm run build

# Expose the port Cloud Run uses
EXPOSE 8080

# Let Cloud Run know which port to use
ENV PORT=8080

# Start the Next.js server
CMD ["npm", "start"]

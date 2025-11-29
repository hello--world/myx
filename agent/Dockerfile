# Build stage
FROM golang:1.21-alpine AS builder

WORKDIR /app

# Install build dependencies
RUN apk add --no-cache git

# Copy go mod files
COPY go.mod go.sum* ./

# Download dependencies
RUN go mod download

# Copy source code
COPY . .

# Build the application
RUN CGO_ENABLED=0 GOOS=linux go build -a -installsuffix cgo -ldflags="-s -w" -o myx-agent main.go

# Final stage
FROM alpine:latest

RUN apk --no-cache add ca-certificates tzdata

WORKDIR /app

# Copy the binary from builder
COPY --from=builder /app/myx-agent /app/myx-agent

# Create config directory
RUN mkdir -p /etc/myx-agent

# Set permissions
RUN chmod +x /app/myx-agent

# Expose port (if needed)
# EXPOSE 8080

# Run the agent
ENTRYPOINT ["/app/myx-agent"]


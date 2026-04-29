YOLO mode is enabled. All tool calls will be automatically approved.
YOLO mode is enabled. All tool calls will be automatically approved.
Attempt 1 failed with status 429. Retrying with backoff... _GaxiosError: [{
  "error": {
    "code": 429,
    "message": "No capacity available for model gemini-3.1-pro-preview on the server",
    "errors": [
      {
        "message": "No capacity available for model gemini-3.1-pro-preview on the server",
        "domain": "global",
        "reason": "rateLimitExceeded"
      }
    ],
    "status": "RESOURCE_EXHAUSTED",
    "details": [
      {
        "@type": "type.googleapis.com/google.rpc.ErrorInfo",
        "reason": "MODEL_CAPACITY_EXHAUSTED",
        "domain": "cloudcode-pa.googleapis.com",
        "metadata": {
          "model": "gemini-3.1-pro-preview"
        }
      }
    ]
  }
}
]
    at Gaxios._request (file:///opt/homebrew/lib/node_modules/@google/gemini-cli/bundle/chunk-IWSCP2GY.js:8578:19)
    at process.processTicksAndRejections (node:internal/process/task_queues:104:5)
    at async _OAuth2Client.requestAsync (file:///opt/homebrew/lib/node_modules/@google/gemini-cli/bundle/chunk-IWSCP2GY.js:10541:16)
    at async CodeAssistServer.requestStreamingPost (file:///opt/homebrew/lib/node_modules/@google/gemini-cli/bundle/chunk-IWSCP2GY.js:277484:17)
    at async CodeAssistServer.generateContentStream (file:///opt/homebrew/lib/node_modules/@google/gemini-cli/bundle/chunk-IWSCP2GY.js:277284:23)
    at async file:///opt/homebrew/lib/node_modules/@google/gemini-cli/bundle/chunk-IWSCP2GY.js:278125:19
    at async file:///opt/homebrew/lib/node_modules/@google/gemini-cli/bundle/chunk-IWSCP2GY.js:255118:23
    at async retryWithBackoff (file:///opt/homebrew/lib/node_modules/@google/gemini-cli/bundle/chunk-IWSCP2GY.js:275082:23)
    at async GeminiChat.makeApiCallAndProcessStream (file:///opt/homebrew/lib/node_modules/@google/gemini-cli/bundle/chunk-IWSCP2GY.js:310999:28)
    at async GeminiChat.streamWithRetries (file:///opt/homebrew/lib/node_modules/@google/gemini-cli/bundle/chunk-IWSCP2GY.js:310837:29) {
  config: {
    url: 'https://cloudcode-pa.googleapis.com/v1internal:streamGenerateContent?alt=sse',
    method: 'POST',
    params: { alt: 'sse' },
    headers: {
      'Content-Type': 'application/json',
      'User-Agent': 'GeminiCLI/0.38.2/gemini-3.1-pro-preview (darwin; arm64; terminal) google-api-nodejs-client/9.15.1',
      Authorization: '<<REDACTED> - See `errorRedactor` option in `gaxios` for configuration>.',
      'x-goog-api-client': 'gl-node/25.9.0'
    },
    responseType: 'stream',
    body: '<<REDACTED> - See `errorRedactor` option in `gaxios` for configuration>.',
    signal: AbortSignal { aborted: false },
    retry: false,
    paramsSerializer: [Function: paramsSerializer],
    validateStatus: [Function: validateStatus],
    errorRedactor: [Function: defaultErrorRedactor]
  },
  response: {
    config: {
      url: 'https://cloudcode-pa.googleapis.com/v1internal:streamGenerateContent?alt=sse',
      method: 'POST',
      params: [Object],
      headers: [Object],
      responseType: 'stream',
      body: '<<REDACTED> - See `errorRedactor` option in `gaxios` for configuration>.',
      signal: [AbortSignal],
      retry: false,
      paramsSerializer: [Function: paramsSerializer],
      validateStatus: [Function: validateStatus],
      errorRedactor: [Function: defaultErrorRedactor]
    },
    data: '[{\n' +
      '  "error": {\n' +
      '    "code": 429,\n' +
      '    "message": "No capacity available for model gemini-3.1-pro-preview on the server",\n' +
      '    "errors": [\n' +
      '      {\n' +
      '        "message": "No capacity available for model gemini-3.1-pro-preview on the server",\n' +
      '        "domain": "global",\n' +
      '        "reason": "rateLimitExceeded"\n' +
      '      }\n' +
      '    ],\n' +
      '    "status": "RESOURCE_EXHAUSTED",\n' +
      '    "details": [\n' +
      '      {\n' +
      '        "@type": "type.googleapis.com/google.rpc.ErrorInfo",\n' +
      '        "reason": "MODEL_CAPACITY_EXHAUSTED",\n' +
      '        "domain": "cloudcode-pa.googleapis.com",\n' +
      '        "metadata": {\n' +
      '          "model": "gemini-3.1-pro-preview"\n' +
      '        }\n' +
      '      }\n' +
      '    ]\n' +
      '  }\n' +
      '}\n' +
      ']',
    headers: {
      'alt-svc': 'h3=":443"; ma=2592000,h3-29=":443"; ma=2592000',
      'content-length': '630',
      'content-type': 'application/json; charset=UTF-8',
      date: 'Tue, 28 Apr 2026 18:55:26 GMT',
      server: 'ESF',
      'server-timing': 'gfet4t7; dur=13456',
      vary: 'Origin, X-Origin, Referer',
      'x-cloudaicompanion-trace-id': '6f21211d32c97905',
      'x-content-type-options': 'nosniff',
      'x-frame-options': 'SAMEORIGIN',
      'x-xss-protection': '0'
    },
    status: 429,
    statusText: 'Too Many Requests',
    request: {
      responseURL: 'https://cloudcode-pa.googleapis.com/v1internal:streamGenerateContent?alt=sse'
    }
  },
  error: undefined,
  status: 429,
  Symbol(gaxios-gaxios-error): '6.7.1'
}
1. **Root cause hypothesis**  
The engine-side REP socket used `asyncio.wait_for` to enforce a timeout on incoming commands, which forcibly cancelled the underlying pyzmq `recv()` coroutine whenever a command didn't arrive in time. Repeatedly cancelling an in-flight `recv()` coroutine degrades the state of pyzmq's asyncio integration with the libzmq reactor, eventually wedging the socket in a permanently broken "awaiting send" state where it ignores all new traffic.

2. **Problematic line in pre-fix code**  
The issue was caused by the following line inside `ZMQCommandServer._serve_loop()` (and identically in `ZMQSubscriber._receive_loop`):  
`raw = await asyncio.wait_for(self._socket.recv(), timeout=1.0)`

3. **Why this produces the ~50 second symptom**  
With a `timeout=1.0`, every second of idle time triggers an `asyncio.CancelledError` on the pending `recv()` coroutine. It takes roughly 50 consecutive cancellations—which translates to ~50 seconds of idle or sparse command traffic—to accumulate enough corrupted state in the pyzmq asyncio integration to fully wedge the socket.

4. **Brief explanation of the correct fix**  
The fix avoids coroutine cancellation entirely by replacing the timeout wrapper with a non-destructive sentinel check: `await self._socket.poll(timeout=1000)`. The `await self._socket.recv()` call is now only executed conditionally when `zmq.POLLIN` is set, meaning a message is guaranteed to be present. Because `poll()` safely times out without mutating socket state and `recv()` is never left hanging to be cancelled, the pyzmq reactor state remains clean.

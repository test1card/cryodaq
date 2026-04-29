YOLO mode is enabled. All tool calls will be automatically approved.
YOLO mode is enabled. All tool calls will be automatically approved.
Attempt 1 failed with status 429. Retrying with backoff... _GaxiosError: [{
  "error": {
    "code": 429,
    "message": "No capacity available for model gemini-2.5-pro on the server",
    "errors": [
      {
        "message": "No capacity available for model gemini-2.5-pro on the server",
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
          "model": "gemini-2.5-pro"
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
      'User-Agent': 'GeminiCLI/0.38.2/gemini-2.5-pro (darwin; arm64; terminal) google-api-nodejs-client/9.15.1',
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
      '    "message": "No capacity available for model gemini-2.5-pro on the server",\n' +
      '    "errors": [\n' +
      '      {\n' +
      '        "message": "No capacity available for model gemini-2.5-pro on the server",\n' +
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
      '          "model": "gemini-2.5-pro"\n' +
      '        }\n' +
      '      }\n' +
      '    ]\n' +
      '  }\n' +
      '}\n' +
      ']',
    headers: {
      'alt-svc': 'h3=":443"; ma=2592000,h3-29=":443"; ma=2592000',
      'content-length': '606',
      'content-type': 'application/json; charset=UTF-8',
      date: 'Wed, 29 Apr 2026 18:45:08 GMT',
      server: 'ESF',
      'server-timing': 'gfet4t7; dur=680',
      vary: 'Origin, X-Origin, Referer',
      'x-cloudaicompanion-trace-id': '69ad52bf795c8bcf',
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
Attempt 2 failed with status 429. Retrying with backoff... _GaxiosError: [{
  "error": {
    "code": 429,
    "message": "No capacity available for model gemini-2.5-pro on the server",
    "errors": [
      {
        "message": "No capacity available for model gemini-2.5-pro on the server",
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
          "model": "gemini-2.5-pro"
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
      'User-Agent': 'GeminiCLI/0.38.2/gemini-2.5-pro (darwin; arm64; terminal) google-api-nodejs-client/9.15.1',
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
      '    "message": "No capacity available for model gemini-2.5-pro on the server",\n' +
      '    "errors": [\n' +
      '      {\n' +
      '        "message": "No capacity available for model gemini-2.5-pro on the server",\n' +
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
      '          "model": "gemini-2.5-pro"\n' +
      '        }\n' +
      '      }\n' +
      '    ]\n' +
      '  }\n' +
      '}\n' +
      ']',
    headers: {
      'alt-svc': 'h3=":443"; ma=2592000,h3-29=":443"; ma=2592000',
      'content-length': '606',
      'content-type': 'application/json; charset=UTF-8',
      date: 'Wed, 29 Apr 2026 18:45:14 GMT',
      server: 'ESF',
      'server-timing': 'gfet4t7; dur=961',
      vary: 'Origin, X-Origin, Referer',
      'x-cloudaicompanion-trace-id': 'fc0fccc0123d1440',
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
Attempt 3 failed with status 429. Retrying with backoff... _GaxiosError: [{
  "error": {
    "code": 429,
    "message": "No capacity available for model gemini-2.5-pro on the server",
    "errors": [
      {
        "message": "No capacity available for model gemini-2.5-pro on the server",
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
          "model": "gemini-2.5-pro"
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
      'User-Agent': 'GeminiCLI/0.38.2/gemini-2.5-pro (darwin; arm64; terminal) google-api-nodejs-client/9.15.1',
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
      '    "message": "No capacity available for model gemini-2.5-pro on the server",\n' +
      '    "errors": [\n' +
      '      {\n' +
      '        "message": "No capacity available for model gemini-2.5-pro on the server",\n' +
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
      '          "model": "gemini-2.5-pro"\n' +
      '        }\n' +
      '      }\n' +
      '    ]\n' +
      '  }\n' +
      '}\n' +
      ']',
    headers: {
      'alt-svc': 'h3=":443"; ma=2592000,h3-29=":443"; ma=2592000',
      'content-length': '606',
      'content-type': 'application/json; charset=UTF-8',
      date: 'Wed, 29 Apr 2026 18:45:23 GMT',
      server: 'ESF',
      'server-timing': 'gfet4t7; dur=167',
      vary: 'Origin, X-Origin, Referer',
      'x-cloudaicompanion-trace-id': 'ec44ff6fae635f46',
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
Attempt 4 failed with status 429. Retrying with backoff... _GaxiosError: [{
  "error": {
    "code": 429,
    "message": "No capacity available for model gemini-2.5-pro on the server",
    "errors": [
      {
        "message": "No capacity available for model gemini-2.5-pro on the server",
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
          "model": "gemini-2.5-pro"
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
      'User-Agent': 'GeminiCLI/0.38.2/gemini-2.5-pro (darwin; arm64; terminal) google-api-nodejs-client/9.15.1',
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
      '    "message": "No capacity available for model gemini-2.5-pro on the server",\n' +
      '    "errors": [\n' +
      '      {\n' +
      '        "message": "No capacity available for model gemini-2.5-pro on the server",\n' +
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
      '          "model": "gemini-2.5-pro"\n' +
      '        }\n' +
      '      }\n' +
      '    ]\n' +
      '  }\n' +
      '}\n' +
      ']',
    headers: {
      'alt-svc': 'h3=":443"; ma=2592000,h3-29=":443"; ma=2592000',
      'content-length': '606',
      'content-type': 'application/json; charset=UTF-8',
      date: 'Wed, 29 Apr 2026 18:45:43 GMT',
      server: 'ESF',
      'server-timing': 'gfet4t7; dur=1682',
      vary: 'Origin, X-Origin, Referer',
      'x-cloudaicompanion-trace-id': '5d5f6b1d2a199ac1',
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
Attempt 5 failed with status 429. Retrying with backoff... _GaxiosError: [{
  "error": {
    "code": 429,
    "message": "No capacity available for model gemini-2.5-pro on the server",
    "errors": [
      {
        "message": "No capacity available for model gemini-2.5-pro on the server",
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
          "model": "gemini-2.5-pro"
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
      'User-Agent': 'GeminiCLI/0.38.2/gemini-2.5-pro (darwin; arm64; terminal) google-api-nodejs-client/9.15.1',
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
      '    "message": "No capacity available for model gemini-2.5-pro on the server",\n' +
      '    "errors": [\n' +
      '      {\n' +
      '        "message": "No capacity available for model gemini-2.5-pro on the server",\n' +
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
      '          "model": "gemini-2.5-pro"\n' +
      '        }\n' +
      '      }\n' +
      '    ]\n' +
      '  }\n' +
      '}\n' +
      ']',
    headers: {
      'alt-svc': 'h3=":443"; ma=2592000,h3-29=":443"; ma=2592000',
      'content-length': '606',
      'content-type': 'application/json; charset=UTF-8',
      date: 'Wed, 29 Apr 2026 18:46:22 GMT',
      server: 'ESF',
      'server-timing': 'gfet4t7; dur=824',
      vary: 'Origin, X-Origin, Referer',
      'x-cloudaicompanion-trace-id': 'a4d425d855b53c2b',
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
Attempt 6 failed with status 429. Retrying with backoff... _GaxiosError: [{
  "error": {
    "code": 429,
    "message": "No capacity available for model gemini-2.5-pro on the server",
    "errors": [
      {
        "message": "No capacity available for model gemini-2.5-pro on the server",
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
          "model": "gemini-2.5-pro"
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
      'User-Agent': 'GeminiCLI/0.38.2/gemini-2.5-pro (darwin; arm64; terminal) google-api-nodejs-client/9.15.1',
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
      '    "message": "No capacity available for model gemini-2.5-pro on the server",\n' +
      '    "errors": [\n' +
      '      {\n' +
      '        "message": "No capacity available for model gemini-2.5-pro on the server",\n' +
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
      '          "model": "gemini-2.5-pro"\n' +
      '        }\n' +
      '      }\n' +
      '    ]\n' +
      '  }\n' +
      '}\n' +
      ']',
    headers: {
      'alt-svc': 'h3=":443"; ma=2592000,h3-29=":443"; ma=2592000',
      'content-length': '606',
      'content-type': 'application/json; charset=UTF-8',
      date: 'Wed, 29 Apr 2026 18:47:00 GMT',
      server: 'ESF',
      'server-timing': 'gfet4t7; dur=736',
      vary: 'Origin, X-Origin, Referer',
      'x-cloudaicompanion-trace-id': 'aeb29a077629037',
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
Attempt 7 failed with status 429. Retrying with backoff... _GaxiosError: [{
  "error": {
    "code": 429,
    "message": "No capacity available for model gemini-2.5-pro on the server",
    "errors": [
      {
        "message": "No capacity available for model gemini-2.5-pro on the server",
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
          "model": "gemini-2.5-pro"
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
      'User-Agent': 'GeminiCLI/0.38.2/gemini-2.5-pro (darwin; arm64; terminal) google-api-nodejs-client/9.15.1',
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
      '    "message": "No capacity available for model gemini-2.5-pro on the server",\n' +
      '    "errors": [\n' +
      '      {\n' +
      '        "message": "No capacity available for model gemini-2.5-pro on the server",\n' +
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
      '          "model": "gemini-2.5-pro"\n' +
      '        }\n' +
      '      }\n' +
      '    ]\n' +
      '  }\n' +
      '}\n' +
      ']',
    headers: {
      'alt-svc': 'h3=":443"; ma=2592000,h3-29=":443"; ma=2592000',
      'content-length': '606',
      'content-type': 'application/json; charset=UTF-8',
      date: 'Wed, 29 Apr 2026 18:47:34 GMT',
      server: 'ESF',
      'server-timing': 'gfet4t7; dur=304',
      vary: 'Origin, X-Origin, Referer',
      'x-cloudaicompanion-trace-id': '25b568167370b476',
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
Attempt 8 failed with status 429. Retrying with backoff... _GaxiosError: [{
  "error": {
    "code": 429,
    "message": "No capacity available for model gemini-2.5-pro on the server",
    "errors": [
      {
        "message": "No capacity available for model gemini-2.5-pro on the server",
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
          "model": "gemini-2.5-pro"
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
      'User-Agent': 'GeminiCLI/0.38.2/gemini-2.5-pro (darwin; arm64; terminal) google-api-nodejs-client/9.15.1',
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
      '    "message": "No capacity available for model gemini-2.5-pro on the server",\n' +
      '    "errors": [\n' +
      '      {\n' +
      '        "message": "No capacity available for model gemini-2.5-pro on the server",\n' +
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
      '          "model": "gemini-2.5-pro"\n' +
      '        }\n' +
      '      }\n' +
      '    ]\n' +
      '  }\n' +
      '}\n' +
      ']',
    headers: {
      'alt-svc': 'h3=":443"; ma=2592000,h3-29=":443"; ma=2592000',
      'content-length': '606',
      'content-type': 'application/json; charset=UTF-8',
      date: 'Wed, 29 Apr 2026 18:48:07 GMT',
      server: 'ESF',
      'server-timing': 'gfet4t7; dur=324',
      vary: 'Origin, X-Origin, Referer',
      'x-cloudaicompanion-trace-id': '25aed32a275146d6',
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
Attempt 9 failed with status 429. Retrying with backoff... _GaxiosError: [{
  "error": {
    "code": 429,
    "message": "No capacity available for model gemini-2.5-pro on the server",
    "errors": [
      {
        "message": "No capacity available for model gemini-2.5-pro on the server",
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
          "model": "gemini-2.5-pro"
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
      'User-Agent': 'GeminiCLI/0.38.2/gemini-2.5-pro (darwin; arm64; terminal) google-api-nodejs-client/9.15.1',
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
      '    "message": "No capacity available for model gemini-2.5-pro on the server",\n' +
      '    "errors": [\n' +
      '      {\n' +
      '        "message": "No capacity available for model gemini-2.5-pro on the server",\n' +
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
      '          "model": "gemini-2.5-pro"\n' +
      '        }\n' +
      '      }\n' +
      '    ]\n' +
      '  }\n' +
      '}\n' +
      ']',
    headers: {
      'alt-svc': 'h3=":443"; ma=2592000,h3-29=":443"; ma=2592000',
      'content-length': '606',
      'content-type': 'application/json; charset=UTF-8',
      date: 'Wed, 29 Apr 2026 18:48:41 GMT',
      server: 'ESF',
      'server-timing': 'gfet4t7; dur=386',
      vary: 'Origin, X-Origin, Referer',
      'x-cloudaicompanion-trace-id': '1d8bd89a26b7f0a9',
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
Attempt 10 failed: No capacity available for model gemini-2.5-pro on the server. Max attempts reached
Error when talking to Gemini API Full report available at: /var/folders/sy/gxxl_n9528qdws_74b5x8mdc0000gn/T/gemini-client-error-Turn.run-sendMessageStream-2026-04-29T18-49-05-482Z.json RetryableQuotaError: No capacity available for model gemini-2.5-pro on the server
    at classifyGoogleError (file:///opt/homebrew/lib/node_modules/@google/gemini-cli/bundle/chunk-IWSCP2GY.js:274525:12)
    at retryWithBackoff (file:///opt/homebrew/lib/node_modules/@google/gemini-cli/bundle/chunk-IWSCP2GY.js:275105:31)
    at process.processTicksAndRejections (node:internal/process/task_queues:104:5)
    at async GeminiChat.makeApiCallAndProcessStream (file:///opt/homebrew/lib/node_modules/@google/gemini-cli/bundle/chunk-IWSCP2GY.js:310999:28)
    at async GeminiChat.streamWithRetries (file:///opt/homebrew/lib/node_modules/@google/gemini-cli/bundle/chunk-IWSCP2GY.js:310837:29)
    at async Turn.run (file:///opt/homebrew/lib/node_modules/@google/gemini-cli/bundle/chunk-IWSCP2GY.js:311329:24)
    at async GeminiClient.processTurn (file:///opt/homebrew/lib/node_modules/@google/gemini-cli/bundle/chunk-IWSCP2GY.js:315405:22)
    at async GeminiClient.sendMessageStream (file:///opt/homebrew/lib/node_modules/@google/gemini-cli/bundle/chunk-IWSCP2GY.js:315518:14)
    at async file:///opt/homebrew/lib/node_modules/@google/gemini-cli/bundle/gemini.js:10168:26
    at async main (file:///opt/homebrew/lib/node_modules/@google/gemini-cli/bundle/gemini.js:15201:5) {
  cause: {
    code: 429,
    message: 'No capacity available for model gemini-2.5-pro on the server',
    details: [ [Object] ]
  },
  retryDelayMs: undefined
}
An unexpected critical error occurred:[object Object]

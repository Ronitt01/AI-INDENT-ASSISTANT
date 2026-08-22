// Dev server config.
//
// strictPort matters here. By default Vite silently moves to the next free port
// when its own is taken, and the backend's CORS allow-list is a fixed set of
// origins — so the drift shows up as a CORS failure on the token request, i.e.
// "Call does nothing", with the actual cause three layers away. Failing to start
// is a much cheaper error than starting on an origin the API will reject.
//
// Override with: VITE_PORT=5180 npm run dev  (add that origin to ALLOWED_ORIGINS)
export default {
  server: {
    port: Number(process.env.VITE_PORT ?? 5180),
    strictPort: true,
  },
};

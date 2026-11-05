module.exports = {
  content: ["./src/**/*.{ts,tsx}", "../proofpay/static/index.html"],
  theme: {
    extend: {
      colors: {
        canvas: "#0B0F19",
        rule: "#1E293B",
        ink: "#F8FAFC",
        overdue: "#F59E0B",
      },
    },
  },
  plugins: [],
};

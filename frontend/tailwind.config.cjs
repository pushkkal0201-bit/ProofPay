module.exports = {
  content: ["./src/**/*.{ts,tsx}", "../proofpay/static/index.html"],
  theme: {
    extend: {
      colors: {
        canvas: "#F9F9F8",
        rule: "#292929",
        ink: "#111111",
        overdue: "#111111",
      },
    },
  },
  plugins: [],
};

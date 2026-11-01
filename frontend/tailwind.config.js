/** Colours are CSS variables (see src/index.css) so light/dark themes swap in one place. */
const v = (name) => `rgb(var(--${name}) / <alpha-value>)`

export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        bg: v('bg'),
        panel: v('panel'),
        panel2: v('panel2'),
        line: v('line'),
        fg: v('fg'),
        muted: v('muted'),
        ink: v('ink'),
        onink: v('onink'),
        late: v('late'),
        absent: v('absent'),
        spoof: v('spoof'),
        // aurora accents: violet, cyan, pink
        glow1: v('glow1'),
        glow2: v('glow2'),
        glow3: v('glow3'),
      },
      fontFamily: {
        sans: ['"Plus Jakarta Sans"', 'system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
        display: ['Sora', '"Plus Jakarta Sans"', 'system-ui', 'sans-serif'],
        hand: ['Kalam', '"Comic Neue"', 'cursive'],
      },
      maxWidth: { prose: '68ch' },
      keyframes: {
        drift: {
          '0%, 100%': { transform: 'translate3d(0, 0, 0) scale(1)' },
          '33%': { transform: 'translate3d(6%, -4%, 0) scale(1.08)' },
          '66%': { transform: 'translate3d(-5%, 5%, 0) scale(0.95)' },
        },
        float: {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-8px)' },
        },
        scan: {
          '0%': { transform: 'translateY(0)', opacity: '0' },
          '10%, 90%': { opacity: '1' },
          '100%': { transform: 'translateY(210px)', opacity: '0' },
        },
        'fade-up': {
          from: { opacity: '0', transform: 'translateY(10px)' },
          to: { opacity: '1', transform: 'none' },
        },
        shimmer: {
          from: { backgroundPosition: '200% 0' },
          to: { backgroundPosition: '-200% 0' },
        },
        'pulse-ring': {
          '0%': { transform: 'scale(0.9)', opacity: '0.7' },
          '100%': { transform: 'scale(1.6)', opacity: '0' },
        },
      },
      animation: {
        drift: 'drift 26s ease-in-out infinite',
        'drift-slow': 'drift 38s ease-in-out infinite reverse',
        float: 'float 6s ease-in-out infinite',
        scan: 'scan 3.4s ease-in-out infinite',
        'fade-up': 'fade-up 480ms cubic-bezier(.2,.7,.2,1) both',
        shimmer: 'shimmer 6s linear infinite',
        'pulse-ring': 'pulse-ring 1.8s ease-out infinite',
      },
    },
  },
  plugins: [],
}

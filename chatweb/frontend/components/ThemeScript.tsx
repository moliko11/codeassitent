/**
 * ThemeScript - applies the stored theme before React hydration to prevent
 * a flash of the wrong theme. Must be a Server Component so the <script>
 * is inlined into the SSR HTML (Client Component <script> tags are inert).
 *
 * Ported from DeepTutor's web/components/ThemeScript.tsx.
 */
export default function ThemeScript() {
  const themeScript = `
    (function() {
      try {
        var stored = localStorage.getItem('chat-template-theme');
        var html = document.documentElement;
        html.classList.remove('dark', 'theme-glass', 'theme-snow');
        if (stored === 'dark') html.classList.add('dark');
        else if (stored === 'glass') html.classList.add('dark', 'theme-glass');
        else if (stored === 'snow') html.classList.add('theme-snow');
        else if (stored === 'light') { /* Cream is the :root default */ }
        else {
          if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
            html.classList.add('dark');
            localStorage.setItem('chat-template-theme', 'dark');
          } else {
            html.classList.add('theme-snow');
            localStorage.setItem('chat-template-theme', 'snow');
          }
        }
      } catch (e) { /* localStorage may be disabled */ }
    })();
  `;
  return (
    <script
      dangerouslySetInnerHTML={{ __html: themeScript }}
      suppressHydrationWarning
    />
  );
}

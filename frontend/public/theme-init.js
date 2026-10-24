/* apply the saved theme before first paint (Dark is the default; storage may be unavailable) */
try { if (localStorage.getItem('plsd-theme') === 'light') document.documentElement.setAttribute('data-theme', 'light'); } catch (e) {}

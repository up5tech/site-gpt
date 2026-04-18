/// <reference types="vite/client" />

declare module '*.module.css' {
  const classes: { [key: string]: string };
  export default classes;
}

declare module '*.less' {
  const content: { [className: string]: string };
  export default content;
}

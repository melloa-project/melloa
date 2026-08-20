import { defineConfig } from "astro/config";
import starlight from "@astrojs/starlight";

export default defineConfig({
  site: "https://melloa-project.github.io",
  base: "/melloa",
  integrations: [
    starlight({
      title: "Melloa",
      description: "Run Melloa as the private home-server system for Melli.",
      customCss: ["./src/styles/site.css"],
      editLink: {
        baseUrl: "https://github.com/melloa-project/melloa/edit/main/docs-site/",
      },
      social: [
        {
          icon: "github",
          label: "GitHub",
          href: "https://github.com/melloa-project/melloa",
        },
      ],
      sidebar: [
        {
          label: "Run Melloa",
          items: [
            { label: "Start here", slug: "index" },
            { label: "Deploy the server", slug: "deploy" },
            { label: "Runtime loop", slug: "runtime-loop" },
            { label: "Self-change loop", slug: "self-change" },
            { label: "Operate it", slug: "operate" },
          ],
        },
        {
          label: "Boundaries",
          items: [{ label: "Trust model", slug: "trust" }],
        },
      ],
    }),
  ],
});

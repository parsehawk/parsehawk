import sitemap from '@astrojs/sitemap';
import starlight from '@astrojs/starlight';
import { defineConfig } from 'astro/config';
import starlightLinksValidator from 'starlight-links-validator';
import starlightLlmsTxt from 'starlight-llms-txt';
import starlightOpenAPI, { createOpenAPISidebarGroup } from 'starlight-openapi';

const apiReferenceGroup = createOpenAPISidebarGroup();

export default defineConfig({
  site: 'https://docs.parsehawk.com',
  trailingSlash: 'always',
  integrations: [
    sitemap(),
    starlight({
      title: 'ParseHawk Developer Docs',
      description:
        'Build private, structured document extraction workflows with the ParseHawk UI, CLI, and REST API.',
      logo: {
        src: './src/assets/logo-mark.svg',
        alt: 'ParseHawk',
      },
      favicon: '/favicon.svg',
      customCss: ['./src/styles/custom.css'],
      editLink: {
        baseUrl: 'https://github.com/parsehawk/parsehawk/edit/main/apps/docs/',
      },
      lastUpdated: true,
      social: [
        {
          icon: 'github',
          label: 'ParseHawk on GitHub',
          href: 'https://github.com/parsehawk/parsehawk',
        },
        {
          icon: 'link',
          label: 'ParseHawk website',
          href: 'https://www.parsehawk.com',
        },
      ],
      head: [
        { tag: 'link', attrs: { rel: 'sitemap', href: '/sitemap-index.xml' } },
        { tag: 'meta', attrs: { property: 'og:site_name', content: 'ParseHawk Developer Docs' } },
        { tag: 'meta', attrs: { property: 'og:type', content: 'website' } },
        { tag: 'meta', attrs: { property: 'og:image', content: '/social-card.png' } },
        { tag: 'meta', attrs: { name: 'twitter:card', content: 'summary_large_image' } },
        { tag: 'meta', attrs: { name: 'theme-color', content: '#ffbe13' } },
      ],
      plugins: [
        starlightOpenAPI([
          {
            base: 'reference/api',
            schema: '../../openapi/openapi.yaml',
            sidebar: {
              label: 'REST API',
              collapsed: true,
              group: apiReferenceGroup,
              operations: { badges: true, labels: 'summary', sort: 'document' },
              tags: { sort: 'document' },
            },
            snippets: {
              operation: {
                clients: { shell: ['curl'], javascript: ['fetch'] },
                default: { target: 'shell', client: 'curl' },
              },
              requestBody: true,
              response: true,
            },
          },
        ]),
        starlightLinksValidator({
          errorOnInvalidHashes: true,
          errorOnRelativeLinks: true,
          // The OpenAPI plugin creates these routes after the content graph the
          // link validator inspects. The docs build still proves the generated
          // index and operation pages exist in the final static artifact.
          exclude: ['/reference/api/**'],
          failOnError: true,
          sameSitePolicy: 'validate',
        }),
        starlightLlmsTxt({
          projectName: 'ParseHawk',
          description:
            'ParseHawk is a local-first document extraction platform with a web UI, CLI, and OpenAPI 3.1 REST API.',
          details:
            'Prefer the tutorials for a first successful extraction, how-to guides for specific tasks, and generated reference pages for exact contracts.',
          customSets: [
            {
              label: 'Tutorials',
              description: 'Guaranteed paths for learning ParseHawk end to end.',
              paths: ['tutorials/**'],
            },
            {
              label: 'Reference',
              description: 'Exact API, CLI, configuration, and schema contracts.',
              paths: ['reference/**'],
            },
          ],
          optionalLinks: [
            {
              label: 'OpenAPI document',
              url: 'https://docs.parsehawk.com/openapi.yaml',
              description: 'The machine-readable ParseHawk REST API contract.',
            },
          ],
        }),
      ],
      sidebar: [
        { label: 'Home', link: '/' },
        {
          label: 'Start here',
          items: [{ slug: 'start-here/choose-installation' }],
        },
        {
          label: 'Tutorials',
          items: [
            { slug: 'tutorials/first-extraction' },
            { slug: 'tutorials/reusable-extractor' },
            { slug: 'tutorials/rest-api' },
          ],
        },
        {
          label: 'How-to guides',
          items: [
            { slug: 'how-to/install-macos' },
            { slug: 'how-to/install-linux-nvidia' },
            { slug: 'how-to/providers' },
            { slug: 'how-to/bundled-runtime' },
            { slug: 'how-to/ollama' },
            { slug: 'how-to/openai' },
            { slug: 'how-to/microsoft-foundry' },
            { slug: 'how-to/openai-compatible' },
            { slug: 'how-to/schemas' },
            { slug: 'how-to/manage-resources' },
            { slug: 'how-to/jobs' },
            { slug: 'how-to/web-ui' },
            { slug: 'how-to/upgrades-backups' },
            { slug: 'how-to/observability' },
            { slug: 'how-to/troubleshooting' },
          ],
        },
        {
          label: 'Explanation',
          items: [
            { slug: 'explanation/architecture' },
            { slug: 'explanation/local-first' },
            { slug: 'explanation/core-concepts' },
            { slug: 'explanation/schema-semantics' },
            { slug: 'explanation/providers-models' },
            { slug: 'explanation/job-lifecycle' },
            { slug: 'explanation/deployment-hardware' },
            { slug: 'explanation/api-stability' },
          ],
        },
        {
          label: 'Reference',
          items: [
            apiReferenceGroup,
            { slug: 'reference/cli' },
            { slug: 'reference/configuration' },
            { slug: 'reference/extraction-schema' },
            { slug: 'reference/provider-matrix' },
            { slug: 'reference/runtime-matrix' },
            { slug: 'reference/errors-and-job-states' },
            { slug: 'reference/paths-ports-defaults' },
            { slug: 'reference/versioning' },
          ],
        },
        {
          label: 'Documentation feedback',
          link: 'https://github.com/parsehawk/parsehawk/issues/new?labels=documentation&title=Docs%3A%20',
        },
      ],
    }),
  ],
});

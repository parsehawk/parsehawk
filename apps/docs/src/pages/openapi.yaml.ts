import type { APIRoute } from 'astro';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';

export const prerender = true;

export const GET: APIRoute = async () => {
  const document = await readFile(resolve(process.cwd(), '../../openapi/openapi.yaml'));
  return new Response(document, {
    headers: {
      'Content-Disposition': 'inline; filename="parsehawk-openapi.yaml"',
      'Content-Type': 'application/yaml; charset=utf-8',
    },
  });
};

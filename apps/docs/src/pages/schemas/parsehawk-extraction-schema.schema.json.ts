import type { APIRoute } from 'astro';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';

export const prerender = true;

export const GET: APIRoute = async () => {
  const schema = await readFile(
    resolve(process.cwd(), '../../docs/schemas/parsehawk-extraction-schema.schema.json'),
  );
  return new Response(schema, {
    headers: {
      'Content-Disposition': 'inline; filename="parsehawk-extraction-schema.schema.json"',
      'Content-Type': 'application/schema+json; charset=utf-8',
    },
  });
};

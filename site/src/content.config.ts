import { defineCollection, z } from 'astro:content';

const blog = defineCollection({
  type: 'content',
  schema: z.object({
    title: z.string(),
    description: z.string(),
    date: z.date(),
    updated: z.date().optional(),
    author: z.string().default('Florent Coulon'),
    image: z.string().optional(),
    tags: z.array(z.string()).default([]),
    linkedin: z.string().optional(), // URL du post LinkedIn source
    draft: z.boolean().default(false),
  }),
});

export const collections = { blog };

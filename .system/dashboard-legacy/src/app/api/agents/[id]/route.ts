import { NextRequest, NextResponse } from 'next/server'
import fs from 'fs'
import path from 'path'

const VAULT_ROOT = process.env.VAULT_ROOT ?? 'D:\\Library\\rpg\\dm\\pathway\\knowledge-base'
const TASKS_PATH = path.join(VAULT_ROOT, '.system', 'tasks.json')

export async function PATCH(req: NextRequest, { params }: { params: { id: string } }) {
  try {
    const body = await req.json() as { model?: string; intervalSeconds?: number }
    const raw = fs.readFileSync(TASKS_PATH, 'utf-8').replace(/^﻿/, '')
    const data = JSON.parse(raw) as { cleanupDays?: number; tasks: Array<{ id: string; model?: string; intervalSeconds?: number; [k: string]: unknown }> }

    const task = data.tasks.find(t => t.id === params.id)
    if (!task) return NextResponse.json({ error: 'agent not found' }, { status: 404 })

    if (body.model !== undefined) {
      if (body.model === '') {
        delete task.model
      } else {
        task.model = body.model
      }
    }

    if (body.intervalSeconds !== undefined) {
      const secs = Number(body.intervalSeconds)
      if (!Number.isFinite(secs) || secs < 60) {
        return NextResponse.json({ error: 'intervalSeconds must be >= 60' }, { status: 400 })
      }
      task.intervalSeconds = secs
    }

    fs.writeFileSync(TASKS_PATH, JSON.stringify(data, null, 2), 'utf-8')
    return NextResponse.json({ ok: true, model: task.model ?? null, intervalSeconds: task.intervalSeconds })
  } catch (e) {
    return NextResponse.json({ error: String(e) }, { status: 500 })
  }
}

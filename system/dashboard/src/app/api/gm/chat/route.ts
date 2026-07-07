import { execFile } from 'child_process'
import fs from 'fs'
import path from 'path'
import { promisify } from 'util'
import { NextRequest, NextResponse } from 'next/server'
import { PROJECT_ROOT } from '@/lib/vault'

export const dynamic = 'force-dynamic'

const execFileAsync = promisify(execFile)

const CHAT_QUEUE = path.join(PROJECT_ROOT, 'system', 'state', 'chat-queue.json')
const RUNNER_ARGS = ['-m', 'nexus.runner']
const PYTHON     = 'python'
const CHAT_TIMEOUT_MS = 120_000

interface ChatQueueItem {
  id: string
  agentName: string
  message: string
  status: 'pending' | 'processing' | 'done' | 'error'
  response: string | null
  error: string | null
  createdAt: string
  updatedAt: string
}

function readQueue(): ChatQueueItem[] {
  try {
    const dir = path.dirname(CHAT_QUEUE)
    if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true })
    if (!fs.existsSync(CHAT_QUEUE)) return []
    return JSON.parse(fs.readFileSync(CHAT_QUEUE, 'utf-8')) as ChatQueueItem[]
  } catch {
    return []
  }
}

function writeQueue(items: ChatQueueItem[]): void {
  const dir = path.dirname(CHAT_QUEUE)
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true })
  const tmp = CHAT_QUEUE + '.tmp'
  fs.writeFileSync(tmp, JSON.stringify(items, null, 2), 'utf-8')
  fs.renameSync(tmp, CHAT_QUEUE)
}

function enqueue(agentName: string, message: string): string {
  const id   = crypto.randomUUID()
  const now  = new Date().toISOString()
  const item: ChatQueueItem = {
    id, agentName, message,
    status: 'pending', response: null, error: null,
    createdAt: now, updatedAt: now,
  }
  const items = readQueue()
  items.push(item)
  writeQueue(items)
  return id
}

function findById(id: string): ChatQueueItem | null {
  return readQueue().find(i => i.id === id) ?? null
}

export async function POST(req: NextRequest) {
  try {
    const body = await req.json() as { message: string; agent: string; context?: string; save?: boolean }
    const { message, agent, context } = body

    if (!message || !agent) {
      return NextResponse.json({ error: 'message and agent required' }, { status: 400 })
    }

    const fullMessage = message + (context ? '\n\nContext:\n' + context : '')
    const chatId = enqueue(agent, fullMessage)

    try {
      await execFileAsync(PYTHON, [...RUNNER_ARGS, '--chat-id', chatId], {
        timeout: CHAT_TIMEOUT_MS,
        env: { ...process.env },
      })
    } catch (execErr) {
      // runner may exit non-zero on LLM error — read queue for actual error
      const item = findById(chatId)
      if (item?.status === 'error') {
        return NextResponse.json({ error: item.error ?? 'Agent dispatch failed' }, { status: 500 })
      }
      // If still pending/processing something went wrong with the subprocess itself
      if (!item || item.status !== 'done') {
        return NextResponse.json({ error: String(execErr) }, { status: 500 })
      }
    }

    const result = findById(chatId)
    if (!result || result.status !== 'done') {
      return NextResponse.json(
        { error: result?.error ?? 'Agent did not return a response' },
        { status: 500 }
      )
    }

    return NextResponse.json({
      role: 'assistant',
      content: result.response,
      timestamp: new Date().toISOString(),
      agent,
    })
  } catch (err) {
    return NextResponse.json({ error: String(err) }, { status: 500 })
  }
}

import { NextResponse } from 'next/server'
import { allReports, readTasks } from '@/lib/vault'

export const dynamic = 'force-dynamic'

export async function GET() {
  return NextResponse.json({
    reports: allReports(),
    tasks: readTasks(),
  })
}

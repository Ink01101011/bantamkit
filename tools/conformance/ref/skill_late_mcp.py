"""Exercise a first skill installed during a real stdio MCP session (#242)."""
import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main(req):
    bed = Path(req['bed'])
    home = bed / 'home'
    project = bed / 'project'
    home.mkdir(parents=True)
    (project / '.bantamkit/memory').mkdir(parents=True)
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home),
               BANTAMKIT_INDEX_DIR=str(bed / 'index'), BANTAMKIT_MEMORY_DIR='')
    params = StdioServerParameters(command=req['command'], args=req['args'],
                                   cwd=str(project), env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            before = await session.call_tool('memory_recall', {'query': 'late-skill'})
            root = project if req['root'] == 'project' else home
            target = root / '.bantamkit/skills/late-skill/SKILL.md'
            target.parent.mkdir(parents=True)
            target.write_text('---\nname: late-skill\ndescription: Diagnose late installation failures\n---\n\n## Steps\n\n1. Verify the late skill sentinel.\n', encoding='utf-8')
            after = await session.call_tool('memory_recall', {'query': 'late-skill'})
            def text(result):
                return '\n'.join(c.text for c in result.content if c.type == 'text')
            return {'absent_before': 'late skill sentinel' not in text(before),
                    'present_after': 'late skill sentinel' in text(after),
                    'error': bool(after.is_error)}


if __name__ == '__main__':
    print(json.dumps(asyncio.run(main(json.load(sys.stdin)))))

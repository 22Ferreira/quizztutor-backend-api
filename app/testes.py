import asyncio
import psycopg

async def main():
    async with await psycopg.AsyncConnection.connect(
        "host=127.0.0.1 port=5432 dbname=tutor_db user=postgres password=postgres"
    ) as conn:
        async with conn.cursor() as cur:
            await cur.execute("SELECT 1;")
            print(await cur.fetchone())

asyncio.run(main())
import asyncio
from solana.rpc.api import Client, Keypair
from solders.keypair import Keypair as SoldersKeypair
from solana.rpc.async_api import AsyncClient
from solders.pubkey import Pubkey
from dotenv import load_dotenv
import os
from create_close_account import fetch_pool_keys, get_token_account, make_swap_instruction, sell_get_token_account
from spl.token.instructions import close_account, CloseAccountParams

# Load environment variables
load_dotenv()
RPC_HTTPS_URL = os.getenv("RPC_HTTPS_URL")
PRIVATE_KEY = os.getenv("PrivateKey")

# Constants
LAMPORTS_PER_SOL = 1000000000

# Initialize Solana clients
client = Client(RPC_HTTPS_URL)
async_client = AsyncClient(RPC_HTTPS_URL)

async def buy(solana_client, token_to_swap_buy, payer, amount):
    # Adapted from buy_swap.py
    mint = Pubkey.from_string(token_to_swap_buy)
    pool_keys = fetch_pool_keys(str(mint))
    amount_in = int(amount * LAMPORTS_PER_SOL)

    # Simplified logic for creating a swap transaction to buy tokens
    swap_token_account, _ = get_token_account(solana_client, payer.public_key(), mint)
    instructions_swap = make_swap_instruction(
        amount_in,
        payer.public_key(),  # Assuming the payer is the source of SOL
        swap_token_account,
        pool_keys,
        mint,
        solana_client,
        payer
    )
    
    transaction = solana_client.create_transaction(instructions_swap)
    await solana_client.send_transaction(transaction, payer)
    print(f"Bought {token_to_swap_buy} for {amount} SOL")
    return True

async def sell_normal(solana_client, token_to_swap_sell, payer):
    # Adapted from sell_swap.py
    mint = Pubkey.from_string(token_to_swap_sell)
    pool_keys = fetch_pool_keys(str(mint))

    # Simplified logic for creating a swap transaction to sell tokens
    swap_token_account, _ = sell_get_token_account(solana_client, payer.public_key(), mint)
    amount_in = 1000  # This should be dynamically determined based on the token's balance

    instructions_swap = make_swap_instruction(
        amount_in,
        swap_token_account,
        payer.public_key(),  # Assuming the payer wants to receive SOL
        pool_keys,
        mint,
        solana_client,
        payer
    )
    
    transaction = solana_client.create_transaction(instructions_swap)
    await solana_client.send_transaction(transaction, payer)
    print(f"Sold {token_to_swap_sell} back to SOL")
    return True

async def trade_cycle(token_to_trade, amount_sol):
    payer = Keypair.from_secret_key(bytes.fromhex(PRIVATE_KEY))

    # Buy tokens
    await buy(client, token_to_trade, payer, amount_sol)
    
    # Wait for 1 minute
    print("Waiting for 1 minute...")
    await asyncio.sleep(60)

    # Sell tokens
    await sell_normal(client, token_to_trade, payer)

async def main():
    token_to_trade = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"  # Token to buy and sell
    amount_sol = 0.01  # Amount of SOL to use for the buy operation
    await trade_cycle(token_to_trade, amount_sol)

if __name__ == "__main__":
    asyncio.run(main())

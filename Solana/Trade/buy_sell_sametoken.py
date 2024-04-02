import asyncio
import os
from dotenv import load_dotenv
from solana.rpc.api import Client
from solana.rpc.async_api import AsyncClient
from solders.pubkey import Pubkey
from create_close_account import fetch_pool_keys, get_token_account, make_swap_instruction, sell_get_token_account

# Load environment variables from .env file
load_dotenv()
RPC_HTTPS_URL = os.getenv("RPC_HTTPS_URL")
PRIVATE_KEY = os.getenv("PrivateKey")
TOKEN_TO_BUY = os.getenv("TOKEN_TO_BUY")
FEE_ADJUSTMENT = float(os.getenv("FEE_ADJUSTMENT", 0.001))  # Default to 0.001 if not set
SLEEP_TIME = int(os.getenv("SLEEP_TIME", 60))  # Default to 60 seconds if not set

# Constants
LAMPORTS_PER_SOL = 1000000000

# Initialize Solana async client
async_client = AsyncClient(RPC_HTTPS_URL)

async def buy(token_to_swap_buy, payer, amount):
    # Adapted from buy_swap.py
    mint = Pubkey.from_string(token_to_swap_buy)
    pool_keys = fetch_pool_keys(str(mint))
    amount_in = int(amount * LAMPORTS_PER_SOL)

    # Simplified logic for creating a swap transaction to buy tokens
    swap_token_account, _ = await get_token_account(async_client, payer.public_key(), mint)
    instructions_swap = make_swap_instruction(
        amount_in,
        payer.public_key(),  # Assuming the payer is the source of SOL
        swap_token_account,
        pool_keys,
        mint,
        async_client,
        payer
    )
    
    transaction = async_client.create_transaction(instructions_swap)
    await async_client.send_transaction(transaction, payer)
    print(f"Bought {token_to_swap_buy} for {amount} SOL")
    return True

async def sell(token_to_swap_sell, payer):
    mint = Pubkey.from_string(token_to_swap_sell)
    pool_keys = fetch_pool_keys(str(mint))

    # Get the token account associated with the payer
    swap_token_account, _ = await sell_get_token_account(async_client, payer.public_key(), mint)

    # Fetch the balance of the token account
    token_account_info = await async_client.get_token_account_balance(swap_token_account)
    token_balance = token_account_info['value']['ui_amount']

    # Use the entire token balance in the swap transaction (subtract a small amount for potential fees)
    amount_in = int(token_balance * LAMPORTS_PER_SOL) - int(FEE_ADJUSTMENT * LAMPORTS_PER_SOL)

    instructions_swap = make_swap_instruction(
        amount_in,
        swap_token_account,
        payer.public_key(),  
        pool_keys,
        mint,
        async_client,
        payer
    )
    
    transaction = async_client.create_transaction(instructions_swap)
    await async_client.send_transaction(transaction, payer)
    print(f"Sold {token_to_swap_sell} back to SOL")
    return True

async def trade_cycle(amount_sol):
    from solders.keypair import Keypair as SoldersKeypair
    payer = SoldersKeypair.from_base58_string(PRIVATE_KEY)

    # Buy tokens
    await buy(TOKEN_TO_BUY, payer, amount_sol)
    
    # Wait for specified time
    print(f"Waiting for {SLEEP_TIME} seconds...")
    await asyncio.sleep(SLEEP_TIME)

    # Sell tokens
    await sell(TOKEN_TO_BUY, payer)

async def main():
    amount_sol = 0.01  # Amount of SOL to use for the buy operation
    await trade_cycle(amount_sol)
    await async_client.close()

if __name__ == "__main__":
    asyncio.run(main())

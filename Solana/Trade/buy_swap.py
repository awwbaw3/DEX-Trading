import asyncio
import datetime
import time
from dotenv import load_dotenv
import os
from solana.rpc.types import TokenAccountOpts
from solana.rpc.commitment import Commitment, Confirmed
from solana.rpc.api import Client, RPCException
from solana.rpc.async_api import AsyncClient
from spl.token.instructions import create_associated_token_account, get_associated_token_address, close_account, \
    CloseAccountParams
import base58
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from create_close_account import fetch_pool_keys, make_swap_instruction
from spl.token.client import Token

def keypair_from_base58(base58_str: str) -> Keypair:
    return Keypair.from_secret_key(base58.b58decode(base58_str))

# Load environment variables
load_dotenv()

config = {
    "RPC_HTTPS_URL": os.getenv("RPC_HTTPS_URL"),
    "PRIVATE_KEY": os.getenv("PRIVATE_KEY"),
    "TOKEN_TO_BUY": os.getenv("TOKEN_TO_BUY"),
    "LAMPORTS_PER_SOL": int(os.getenv("LAMPORTS_PER_SOL", 1000000000)),
    "MAX_RETRIES": int(os.getenv("MAX_RETRIES", 5)),
    "RETRY_DELAY": int(os.getenv("RETRY_DELAY", 3)),
    "AMOUNT_SOL": float(os.getenv("AMOUNT_SOL", 0.01))  # Default to 0.01 if not set
}



# Initialize clients
async_solana_client = AsyncClient(config["RPC_HTTPS_URL"])

def getTimestamp():
    timeStampData = datetime.datetime.now()
    return f"[{timeStampData.strftime('%H:%M:%S.%f')[:-3]}]"

async def get_token_account(ctx, owner: Pubkey, mint: Pubkey):
    try:
        account_data = await ctx.get_token_accounts_by_owner(owner, TokenAccountOpts(mint=mint))
        return account_data['result']['value'][0]['pubkey'], None
    except Exception as e:
        print(f"Error getting token account: {e}")
        swap_associated_token_address = get_associated_token_address(owner, mint)
        swap_token_account_Instructions = create_associated_token_account(owner, owner, mint)
        return swap_associated_token_address, swap_token_account_Instructions

async def buy(token_to_swap_buy, payer, amount):
    # Ensure you're using 'async_client' that is initialized with 'config["RPC_HTTPS_URL"]'
    async_client = AsyncClient(config["RPC_HTTPS_URL"])
    
    mint = Pubkey.from_string(token_to_swap_buy)
    pool_keys = fetch_pool_keys(str(mint))
    
    # Use 'LAMPORTS_PER_SOL' from the 'config' dictionary
    lamports_per_sol = config["LAMPORTS_PER_SOL"]
    amount_in = int(amount * lamports_per_sol)

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

    transaction = await async_client.create_transaction(instructions_swap)
    await async_client.send_transaction(transaction, payer)
    print(f"Bought {token_to_swap_buy} for {amount} SOL")
    return True


# The main function remains unchanged


async def main():
    # Existing initialization code...
    private_key_str = config["PRIVATE_KEY"]
    if not private_key_str:
        raise ValueError("PrivateKey not found in environment variables. Please ensure it is defined.")
    
    # Initialize 'payer' as a Keypair object from the private key string
    payer = keypair_from_base58(private_key_str)
    print(f"Payer PublicKey: {payer.public_key()}") 

    token_toBuy = config["TOKEN_TO_BUY"]
    amount_SOL = config["AMOUNT_SOL"]

    # Pass the 'payer' Keypair object instead of 'private_key_str' to the 'buy' function
    buy_transaction = await buy(token_toBuy, payer, amount_SOL)
    if buy_transaction:
        print("Buy transaction successful.")
    else:
        print("Buy transaction failed.")


if __name__ == "__main__":
    asyncio.run(main())

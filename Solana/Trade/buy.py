import asyncio
import datetime
import time
from solana.rpc.types import TokenAccountOpts
from solders.pubkey import Pubkey
from solana.rpc.commitment import Commitment, Confirmed, Finalized
from solana.rpc.api import RPCException
from solana.rpc.api import Client, Keypair
from solana.rpc.async_api import AsyncClient
from solders.compute_budget import set_compute_unit_price,set_compute_unit_limit
from spl.token.instructions import create_associated_token_account, get_associated_token_address, close_account, \
    CloseAccountParams
from create_close_account import  fetch_pool_keys,  make_swap_instruction
from spl.token.client import Token
from spl.token.core import _TokenCore

from dotenv import dotenv_values, find_dotenv
config = dotenv_values(find_dotenv())

async_solana_client= AsyncClient(config["RPC_HTTPS_URL"]) #Enter your API KEY in .env file

solana_client = Client(config["RPC_HTTPS_URL"])

LAMPORTS_PER_SOL = float(config["LAMPORTS_PER_SOL"])
MAX_RETRIES = float(config["MAX_RETRIES"])
RETRY_DELAY = float(config["RETRY_DELAY"])
TARGET_TOKEN = config["TARGET_TOKEN"]
AMOUNT_SOL = float(config["AMOUNT_SOL"])
COMPUTEUNITPRICE = int(config["COMPUTEUNITPRICE"])
COMPUTEUNITLIMIT = int(config["COMPUTEUNITLIMIT"])

#You can use getTimeStamp With Print Statments to evaluate How fast your transactions are confirmed

def getTimestamp():
    while True:
        timeStampData = datetime.datetime.now()
        currentTimeStamp = "[" + timeStampData.strftime("%H:%M:%S.%f")[:-3] + "]"
        return currentTimeStamp

def adjust_for_fees(amount, slippage, fee_adjustment):
    adjusted_amount = amount - (amount * slippage + fee_adjustment)
    print(f"{getTimestamp()} Adjusted amount: {adjusted_amount}")
    return adjusted_amount

async def get_transaction_with_timeout(client, txid, commitment=Finalized, timeout=10):
    # Wrap the synchronous get_transaction call in a coroutine
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, client.get_transaction, txid, "json")

async def get_token_account(ctx,
                                owner: Pubkey.from_string,
                                mint: Pubkey.from_string):
        try:
            account_data = await ctx.get_token_accounts_by_owner(owner, TokenAccountOpts(mint))
            return account_data.value[0].pubkey, None
        except:
            print(f"Error getting token account: {e}")
            swap_associated_token_address = get_associated_token_address(owner, mint)
            swap_token_account_Instructions = create_associated_token_account(owner, owner, mint)
            return swap_associated_token_address, swap_token_account_Instructions

async def buy(solana_client, TARGET_TOKEN, payer, amount):

    retry_count = 0
    while retry_count < MAX_RETRIES:
        try:
            # Convert environment variables to correct types
            SLIPPAGE = float(config["SLIPPAGE"])
            FEE_ADJUSTMENT = float(config["FEE_ADJUSTMENT"])
            
            mint = Pubkey.from_string(TARGET_TOKEN)
            pool_keys = fetch_pool_keys(str(mint))
            
            # Adjust the amount for slippage and fees
            amount_in = adjust_for_fees(amount * LAMPORTS_PER_SOL, SLIPPAGE, FEE_ADJUSTMENT)
            amount_in = int(amount_in)  # Ensure it's an integer for the transaction
            
            accountProgramId = solana_client.get_account_info_json_parsed(mint)
            TOKEN_PROGRAM_ID = accountProgramId.value.owner

            balance_needed = Token.get_min_balance_rent_for_exempt_for_account(solana_client)
            swap_associated_token_address, swap_token_account_Instructions = await get_token_account(async_solana_client, payer.pubkey(), mint)
            WSOL_token_account, swap_tx, payer, Wsol_account_keyPair, opts, = _TokenCore._create_wrapped_native_account_args(
                TOKEN_PROGRAM_ID, payer.pubkey(), payer, amount_in,
                False, balance_needed, Commitment("confirmed"))    
            instructions_swap = make_swap_instruction(amount_in,
                                                      WSOL_token_account,
                                                      swap_associated_token_address,
                                                      pool_keys,
                                                      mint,
                                                      solana_client,
                                                      payer)
            params = CloseAccountParams(account=WSOL_token_account, dest=payer.pubkey(), owner=payer.pubkey(),
                                        program_id=TOKEN_PROGRAM_ID)
            closeAcc = (close_account(params))
            if swap_token_account_Instructions != None:
                # recent_blockhash = solana_client.get_latest_blockhash(commitment="confirmed") #Without adding hash to instructions txn always goes through
                # swap_tx.recent_blockhash = recent_blockhash.value.blockhash
                swap_tx.add(swap_token_account_Instructions)

            #compute unit price and comute unit limit gauge your gas fees more explanations on how to calculate in a future article

            swap_tx.add(instructions_swap,set_compute_unit_price(COMPUTEUNITPRICE),set_compute_unit_limit(COMPUTEUNITLIMIT),closeAcc)
            print("Transaction Instructions:")
            for instruction in swap_tx.instructions:
                print(f"Program ID: {instruction.program_id}")
    
                # For `solders`, accounts might not be directly accessible via a `keys` attribute.
                # If you're iterating over `solders` instructions, you might need to adjust how you access accounts.
                # This is a generic approach and might need adjustments.
                print("Accounts:")
                for account_meta in instruction.accounts:
                    print(f"  - Pubkey: {account_meta.pubkey}, Is Signer: {account_meta.is_signer}, Is Writable: {account_meta.is_writable}")
    
                # Assuming data is a byte array; display it in hex format
                print(f"Data (hex): {instruction.data.hex()}")


            print(f"\nRecent Blockhash: {swap_tx.recent_blockhash}")

            txn = solana_client.send_transaction(swap_tx, payer,Wsol_account_keyPair)
            txid_string_sig = txn.value
            if txid_string_sig:
                print("Waiting For Transaction Confirmation .......")

                print(f"Transaction Signature: https://solscan.io/tx/{txid_string_sig}")
                # Await transaction confirmation with a timeout
                await asyncio.wait_for(
                    get_transaction_with_timeout(solana_client, txid_string_sig, commitment="finalized", timeout=10),
                    timeout=15
                )
                print("Transaction Confirmed")
                # return txid_string_sig
                return True
        except asyncio.TimeoutError:
            print("Transaction confirmation timed out. Retrying...")
            retry_count += 1
            time.sleep(RETRY_DELAY)
        except RPCException as e:
            print(f"RPC Error: [{e.args[0].message}]... Retrying...")
            retry_count += 1
            time.sleep(RETRY_DELAY)
        except Exception as e:
            print(f"Unhandled exception: {e}. Retrying...")
            retry_count = MAX_RETRIES
            return False

    print("Failed to confirm transaction after maximum retries.")
    return False



##
async def main():

    target_Token=config["TARGET_TOKEN"] #Enter token you wish to buy here
    payer = Keypair.from_base58_string(config["PRIVATE_KEY"])
    print(payer.pubkey())
    buy_transaction=await buy(solana_client, target_Token, payer, AMOUNT_SOL) #Enter amount of sol you wish to spend
    print(buy_transaction)

asyncio.run(main())
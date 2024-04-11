from datetime import datetime
from time import sleep
import logging
import asyncio
from typing import AsyncIterator, Tuple
from asyncstdlib import enumerate
from pip._vendor.typing_extensions import Iterator
from solana.rpc.core import RPCException
from spl.token.instructions import create_associated_token_account, get_associated_token_address
from spl.token.client import Token
from spl.token.core import _TokenCore
from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price
from spl.token.instructions import close_account, CloseAccountParams
from solders.pubkey import Pubkey
from solders.rpc.config import RpcTransactionLogsFilterMentions
from solana.rpc.websocket_api import connect
from solana.rpc.commitment import Finalized
from solana.exceptions import SolanaRpcException
from solana.transaction import AccountMeta
from solana.rpc.types import TokenAccountOpts
from solders.instruction import Instruction
from websockets.exceptions import ConnectionClosedError, ProtocolError
from typing import List
import time

# Type hinting imports
from solana.rpc.commitment import Commitment
from solana.rpc.websocket_api import SolanaWsClientProtocol
from solders.rpc.responses import RpcLogsResponse, SubscriptionResult, LogsNotification, GetTransactionResp
from solders.signature import Signature
from solders.transaction_status import UiPartiallyDecodedInstruction, ParsedInstruction
from solana.rpc.api import Client, Keypair
import base64
import pytz
import binascii
import re
import json
import requests
from construct import Container
from construct import Bytes, Int8ul, Int64ul, Padding
from construct import Struct as cStruct
from construct import BitsInteger, BitsSwapped, BitStruct, Const, Flag


#TODO: [][][][][][][][][] CONFIGURE THIS TO YOUR OWN PERSONAL SETTINGS [][][][][][][][][]
#YOUR PRIVATE KEY (DO NOT SHARE WITH ANYONE)
payer = Keypair.from_base58_string(
    'ABCDEFGHIJKLMNOPQRSTUVWXYZABCDEFGHIJKLMNOPQRSTUVWXYZABCDEFGHIJKLMNOPQRSTUVWXYZABCD')  # 88 Character private key,
#BOT SETTINGS:
GAS_LIMIT = 400_000 # Python considers the character _ is a decimal separator in a number.
GAS_PRICE = 200_000 # That is, the number 200_000 will be equal to the number 200000
# You will pay 0.00009 SOL ($0.015) overall per txn

# this is the amount your bot will buy when it finds a new token
amount = 0.0003  # amount is in SOLANA; about 0.0003 sol is about $0.05 cents in USD.

# ONLY BUY IF PAIR IS LESS THAN {WHEN_TO_BUY} SECONDS
WHEN_TO_BUY = 10 #Only buys tokens that are less than 10s old


#FUTURE MINT SETTINGS
FUTURE_MINT_EXPIRATION = 300 # removes pairs exceeding 300s (i.e. >5 min OLD) from future_mint.json
#For future mints you'll need a seperate script to check and buy them

#THE CONFIRMATION BREAKS BEFORE THESE SETTINGS EVEN WORK
CONFIRM_ATTEMPT_SLEEP_TIME = 1 #1 SECOND
CONFIRM_RETRY_LIMIT = 10

#TODO: [][][][][][][][][][][][][][]END OF PERSONAL SETTINGS[][][][][][][][][][][][][][][][][][][]

#TODO: YOU WILL NEED TO CREATE THESE FOUR JSON FILES IN THE SAME FOLDER AS YOUR PYTHON SCRIPT
pool_key_storage = "my_pools.json"
future_mint = "future_mint.json"
messages_log = "messages.json"
transactions_log = "transactions.json"


# Raydium Liquidity Pool V4
RaydiumLPV4 = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
URI = "https://api.mainnet-beta.solana.com"  # "https://api.devnet.solana.com" | "https://api.mainnet-beta.solana.com"
WSS = "wss://api.mainnet-beta.solana.com"  # "wss://api.devnet.solana.com" | "wss://api.mainnet-beta.solana.com"
solana_client = Client(URI)
METADATA_PROGRAM_ID = "metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s"
LAMPORTS_PER_SOL = 1000000000
AMM_PROGRAM_ID = Pubkey.from_string('675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8')
SERUM_PROGRAM_ID = Pubkey.from_string('srmqPvymJeFKQ4zGQed1GFppgkRHL9kaELCbyksJtPX')

log_instruction = "init_pc_amount"
# log_instruction = "initialize2"

# Init logging
logging.basicConfig(filename='app.log', filemode='a', level=logging.DEBUG)

async def main():
    """The client as an infinite asynchronous iterator:"""
    async for websocket in connect(WSS):
        try:
            subscription_id = await subscribe_to_logs(
                websocket,
                RpcTransactionLogsFilterMentions(RaydiumLPV4),
                Finalized
            )
            # Change level debugging to INFO
            logging.getLogger().setLevel(logging.INFO)  # Logging
            async for i, signature in enumerate(process_messages(websocket, log_instruction)):  # type: ignore
                logging.info(f"{i=}")  # Logging
                try:
                    await get_tokens(signature,
                               RaydiumLPV4)  # AttributeError: 'NoneType' object has no attribute 'transaction'

                except (AttributeError, SolanaRpcException) as err:
                    # Omitting httpx.HTTPStatusError: Client error '429 Too Many Requests'
                    # Sleep 5 sec, and try connect again
                    # Start logging
                    logging.exception(err)
                    logging.info("sleep for 5 seconds and try again")
                    # End logging
                    sleep(5)
                    continue
        except (ProtocolError, ConnectionClosedError) as err:
            # Restart socket connection if ProtocolError: invalid status code
            logging.exception(err)  # Logging
            print(f"Danger! Danger!", err)
            continue
        except KeyboardInterrupt:
            if websocket:
                await websocket.logs_unsubscribe(subscription_id)

#pairfinder
async def subscribe_to_logs(websocket: SolanaWsClientProtocol,
                            mentions: RpcTransactionLogsFilterMentions,
                            commitment: Commitment) -> int:
    await websocket.logs_subscribe(
        filter_=mentions,
        commitment=commitment
    )
    first_resp = await websocket.recv()
    return get_subscription_id(first_resp)  # type: ignore

#pairfinder
def get_subscription_id(response: SubscriptionResult) -> int:
    return response[0].result

#pairfinder
async def process_messages(websocket: SolanaWsClientProtocol,
                           instruction: str) -> AsyncIterator[Signature]:
    """Async generator, main websocket's loop"""
    async for idx, msg in enumerate(websocket):
        value = get_msg_value(msg)
        if not idx % 100:
            print(f"{idx=}")
        for log in value.logs:
            if instruction not in log:
                continue
            # Start logging
            logging.info(value.signature)
            logging.info(log)
            # Logging to messages.json
            with open(messages_log, 'a', encoding='utf-8') as raw_messages:
                raw_messages.write(f"signature: {value.signature} \n")
                raw_messages.write(msg[0].to_json())
                raw_messages.write("\n ########## \n")
            # End logging
            yield value.signature


#pairfinder
def get_msg_value(msg: List[LogsNotification]) -> RpcLogsResponse:
    return msg[0].result.value

'''[][][][][][][][][][][][][][][] LAYOUTS [][][][][][][][][][][][][][][]'''
# MY LAYOUT
# We will use a bitstruct with 64 bits instead of the widebits implementation in serum-js.
ACCOUNT_FLAGS_LAYOUT = BitsSwapped(  # Swap to little endian
    BitStruct(
        "initialized" / Flag,
        "market" / Flag,
        "open_orders" / Flag,
        "request_queue" / Flag,
        "event_queue" / Flag,
        "bids" / Flag,
        "asks" / Flag,
        Const(0, BitsInteger(57)),  # Padding
    )
)

#MY LAYOUT
MARKET_LAYOUT = cStruct(
    Padding(5),
    "account_flags" / ACCOUNT_FLAGS_LAYOUT,
    "own_address" / Bytes(32),
    "vault_signer_nonce" / Int64ul,
    "base_mint" / Bytes(32),
    "quote_mint" / Bytes(32),
    "base_vault" / Bytes(32),
    "base_deposits_total" / Int64ul,
    "base_fees_accrued" / Int64ul,
    "quote_vault" / Bytes(32),
    "quote_deposits_total" / Int64ul,
    "quote_fees_accrued" / Int64ul,
    "quote_dust_threshold" / Int64ul,
    "request_queue" / Bytes(32),
    "event_queue" / Bytes(32),
    "bids" / Bytes(32),
    "asks" / Bytes(32),
    "base_lot_size" / Int64ul,
    "quote_lot_size" / Int64ul,
    "fee_rate_bps" / Int64ul,
    "referrer_rebate_accrued" / Int64ul,
    Padding(7),
)

#MY LAYOUT
MINT_LAYOUT = cStruct(Padding(44), "decimals" / Int8ul, Padding(37))


'''[][][][][][][][][][][][][][][] Market Info Extractor [][][][][][][][][][][][][][][]'''
def make_parsed_market(bytes_data: bytes) -> Container:
    parsed_market = MARKET_LAYOUT.parse(bytes_data)
    # TODO: add ownAddress check!

    if not parsed_market.account_flags.initialized or not parsed_market.account_flags.market:
        raise Exception("Invalid market")
        # TODO: THIS EXCEPTION STOPS THE PROGRAM, NEED TO FIND A WAY TO PREVENT IT
    return parsed_market

async def fetchMarketInfo(marketId: Pubkey):
    # https://stackoverflow.com/questions/39209872/decode-base64-string-to-byte-array
    res = solana_client.get_account_info(marketId)
    try:
        data = res.value.data
        encoded = binascii.b2a_base64(data)  # <--Jackpot!
        bytes_data = base64.decodebytes(encoded)
        parsed_market = make_parsed_market(bytes_data)  # exception raiser
    except Exception:
        parsed_market = "failed"

    return parsed_market


'''[][][][][][][][][][][][][][][] Pool Key Extractor [][][][][][][][][][][][][][][]'''
# Custom Script to Parse Account and Market data for near INSTANT transactions
async def parsePoolInfoFromLpTransaction(
        instruction: UiPartiallyDecodedInstruction,
        signature: Signature):
    accounts = instruction.accounts
    print("START")
    #baseMint = ""
    if accounts[8] != "So11111111111111111111111111111111111111112":
        baseMint = accounts[8]
        quoteMint = accounts[9]
    else:
        quoteMint = accounts[8]
        baseMint = accounts[9]

    # Added this because I was occasionally getting it wrong despite the check above
    if baseMint == "So11111111111111111111111111111111111111112":
        baseMint = quoteMint

    withdrawQueue = Pubkey.from_string("11111111111111111111111111111111")

    lpDecimals = ""
    baseDecimals = ""
    quoteDecimals = ""

    transaction_0 = solana_client.get_transaction(
        signature,
        encoding="jsonParsed",
        max_supported_transaction_version=0
    )
    meta_data = get_meta(transaction_0)

    '''print('[][][][][][][][][][][][][][baseDecimals and quoteDecimals][][][][][][][][][][][][][][][][][][][][][]')'''

    try:
        preBalances = meta_data.pre_token_balances
        # find baseDecimals (it varies)
        if preBalances[0].mint == baseMint:
            baseDecimals = preBalances[0].ui_token_amount.decimals
            quoteDecimals = preBalances[1].ui_token_amount.decimals
        if preBalances[1].mint == baseMint:
            baseDecimals = preBalances[1].ui_token_amount.decimals
            quoteDecimals = preBalances[0].ui_token_amount.decimals
        else:
            print("no match")
    except:
        print('Failed to find base tokens preTokenBalance entry to parse the base tokens decimals')

    '''print('[][][][][][][][][][][][][][openTime][][][][][][][][][][][][][][][][][][][][][]')'''
    re_arrange = []
    lpInitializationLogEntryInfo = meta_data.log_messages
    for lpinit_ in lpInitializationLogEntryInfo:
        try:
            re_arrange = re.findall(r"\{(.*?)\}", lpinit_)
            if not re_arrange:
                pass
            else:
                break
        except Exception as e:
            print(f"Exception (openTime): {e}")
            pass
    try:
        my_list = re_arrange[0].split(",")
        open_time_raw = my_list[1].split("open_time: ", 1)[1]
        open_time_int = int(open_time_raw)  # raw
        now = datetime.now()
        current_ts = datetime.timestamp(now)
        fmt_regular = '%Y-%m-%d %I:%M:%S %p'
        local_tz = pytz.timezone('US/Eastern')
        utc_dt = datetime.fromtimestamp(open_time_int, tz=local_tz).strftime(fmt_regular)
        print(f"Open Time: {utc_dt}")

        today_date = datetime.now(tz=local_tz).strftime(fmt_regular)
        print(f"Date Time: {today_date}")

        if open_time_int > current_ts:
            print("Future mint")
            print(f"Will be minted in {open_time_int - current_ts} seconds.")
        elif current_ts > open_time_int:
            print("Already minted")
            print(f"Minted {current_ts - open_time_int} seconds ago.")


    except:
        pass

    '''print('[][][][][][][][][][][][][][lpDecimals][][][][][][][][][][][][][][][][][][][][][]')'''

    lpMintInitInstruction = ""
    innerInstructions_0 = meta_data.inner_instructions  # initializeMint
    lpReserve = -69
    lpReserve_ = -69
    print(f"lpMint: {accounts[7]}")
    for x in innerInstructions_0:
        for y in x.instructions:
            try:
                if Pubkey.from_string(y.parsed['info']['mint']) == accounts[7] and y.parsed['type'] == 'initializeMint':
                    lpDecimals = y.parsed['info']['decimals']
                elif Pubkey.from_string(y.parsed['info']['mint']) == accounts[7] and y.parsed['type'] == 'mintTo':
                    lpReserve = y.parsed['info']['amount']
                    lpReserve_ = y.parsed['info']['amount']
                else:
                    pass
            except:
                pass

            try:
                if Pubkey.from_string(y.parsed['type']) == accounts[7] and y.parsed['type'] == 'initializeMint':
                    lpDecimals = y.parsed['info']['decimals']
                else:
                    pass
            except:
                pass

    '''print('[][][][][][][][][][][][][][fetchMarketInfo][][][][][][][][][][][][][][][][][][][][][]')'''
    # Get account info for market info returns (seemingly) unusable raw binary data.

    marketInfo = await fetchMarketInfo(accounts[16])
    #if at first you don't succeed try again
    if marketInfo == "failed":
        marketInfo = await fetchMarketInfo(accounts[16])
    print('========================== What Parsing RAW Data looks like ======================')
    print(marketInfo)


    '''print('[][][][][][][][][][][][][][The END][][][][][][][][][][][][][][][][][][][][][]')'''
    my_pools = {
        'id': str(accounts[4]),  # NEED
        'authority': str(accounts[5]),  # NEED
        'baseMint': str(baseMint),  # NEED
        'baseDecimals': str(baseDecimals),  # NEED
        'quoteMint': str(quoteMint),  # NEED
        'quoteDecimals': str(quoteDecimals),  # NEED
        'lpMint': str(accounts[7]),  # NEED
        'openOrders': str(accounts[6]),  # NEED
        'targetOrders': str(accounts[13]),  # NEED
        'baseVault': str(accounts[10]),  # NEED
        'quoteVault': str(accounts[11]),  # NEED
        'marketId': str(accounts[16]),  # NEED
        'marketBaseVault': str(Pubkey(marketInfo.base_vault)),  # NEED
        'marketQuoteVault': str(Pubkey(marketInfo.quote_vault)),  # NEED
        'marketAuthority': str(Pubkey(marketInfo.own_address)),  # NEED ASSUME OWNER ADDRESS
        'marketBids': str(Pubkey(marketInfo.bids)),  # NEED
        'marketAsks': str(Pubkey(marketInfo.asks)),  # NEED
        'marketEventQueue': str(Pubkey(marketInfo.event_queue)),  # NEED
        'tokenProgramID': str(accounts[0]),  # NEED
        'lpDecimals': str(lpDecimals),  # EXTRA
        'version': str(4),  # EXTRA
        'programId': str(RaydiumLPV4),  # EXTRA
        'withdrawQueue': str(withdrawQueue),  # EXTRA
        'marketVersion': str(3),  # EXTRA
        'marketProgramId': str(accounts[15]),  # EXTRA
        'openTime': str(open_time_int), # WANT TO KNOW FOR FUTURE MINT
        'lpReserve': str(lpReserve_)  # WANT TO KNOW FOR lpLockedPct
    }

    # Store pool_keys to a JSON file
    timestamp_ts1 = datetime.timestamp(now)
    print("Saving pool data to 'my_pools.json'")

    with open(pool_key_storage, 'r+') as file:
        file_data = json.load(file)
        file_data.append(my_pools)
        file.seek(0)
        json.dump(file_data, file, indent=4)
    timestamp_ts2 = datetime.timestamp(now)
    print(f"Saving Completed in {timestamp_ts2 - timestamp_ts1} seconds..")
    print(
        f"================================MY POOL KEYS:===================================\n{json.dumps(my_pools, indent=4)}")
    return my_pools


#Pairfinder
def get_instructions(
        transaction: GetTransactionResp
) -> List[UiPartiallyDecodedInstruction | ParsedInstruction]:
    instructions = transaction \
        .value \
        .transaction \
        .transaction \
        .message \
        .instructions
    return instructions

#NOT from PairFinder - I created this to extract meta data
def get_meta(
        transaction: GetTransactionResp
) -> List[UiPartiallyDecodedInstruction | ParsedInstruction]:
    meta = transaction \
        .value \
        .transaction \
        .meta
    return meta

'''[][][][][][][][][][][][][][][] BUY FUNCTIONS [][][][][][][][][][][][][][][]'''

#Pairfinder
def extract_pool_info(pools_list: list, mint: str) -> dict:
    for pool in pools_list:

        if pool['baseMint'] == mint and pool['quoteMint'] == 'So11111111111111111111111111111111111111112':
            #print(f"MATCH FOUND:\n{pool}")
            return pool
        elif pool['quoteMint'] == mint and pool['baseMint'] == 'So11111111111111111111111111111111111111112':
            return pool
    raise Exception(f'{mint} pool not found!')

#Pairfinder
SWAP_LAYOUT = cStruct(
    "instruction" / Int8ul,
    "amount_in" / Int64ul,
    "min_amount_out" / Int64ul
)

#Pairfinder
def make_swap_instruction(amount_in: int, token_account_in: Pubkey.from_string, token_account_out: Pubkey.from_string,
                          accounts: dict, mint, ctx, owner) -> Instruction:
    tokenPk = mint
    try:
        print('attempt to pull accountProgramID.value.owner')
        accountProgramId = ctx.get_account_info_json_parsed(tokenPk)
        TOKEN_PROGRAM_ID = accountProgramId.value.owner
        print(f"(No Problem) TOKEN_PROGRAM_ID: {TOKEN_PROGRAM_ID}")
    except Exception as e:
        print(f"Exception: {e}")
        #Try this
        TOKEN_PROGRAM_ID = Pubkey.from_string('TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA')

    keys = [
        AccountMeta(pubkey=TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
        AccountMeta(pubkey=accounts["amm_id"], is_signer=False, is_writable=True),
        AccountMeta(pubkey=accounts["authority"], is_signer=False, is_writable=False),
        AccountMeta(pubkey=accounts["open_orders"], is_signer=False, is_writable=True),
        AccountMeta(pubkey=accounts["target_orders"], is_signer=False, is_writable=True),
        AccountMeta(pubkey=accounts["base_vault"], is_signer=False, is_writable=True),
        AccountMeta(pubkey=accounts["quote_vault"], is_signer=False, is_writable=True),
        AccountMeta(pubkey=SERUM_PROGRAM_ID, is_signer=False, is_writable=False),
        AccountMeta(pubkey=accounts["market_id"], is_signer=False, is_writable=True),
        AccountMeta(pubkey=accounts["bids"], is_signer=False, is_writable=True),
        AccountMeta(pubkey=accounts["asks"], is_signer=False, is_writable=True),
        AccountMeta(pubkey=accounts["event_queue"], is_signer=False, is_writable=True),
        AccountMeta(pubkey=accounts["market_base_vault"], is_signer=False, is_writable=True),
        AccountMeta(pubkey=accounts["market_quote_vault"], is_signer=False, is_writable=True),
        AccountMeta(pubkey=accounts["market_authority"], is_signer=False, is_writable=False),
        AccountMeta(pubkey=token_account_in, is_signer=False, is_writable=True),  # UserSourceTokenAccount
        AccountMeta(pubkey=token_account_out, is_signer=False, is_writable=True),  # UserDestTokenAccount
        AccountMeta(pubkey=owner.pubkey(), is_signer=True, is_writable=False)  # UserOwner
    ]

    data = SWAP_LAYOUT.build(
        dict(
            instruction=9,
            amount_in=int(amount_in),
            min_amount_out=0
        )
    )
    return Instruction(AMM_PROGRAM_ID, data, keys)

#Pairfinder
def get_token_account(ctx,
                      owner: Pubkey.from_string,
                      mint: Pubkey.from_string):
    try:
        account_data = ctx.get_token_accounts_by_owner(owner, TokenAccountOpts(mint))
        return account_data.value[0].pubkey, None
    except:
        swap_associated_token_address = get_associated_token_address(owner, mint)
        swap_token_account_Instructions = create_associated_token_account(owner, owner, mint)
        return swap_associated_token_address, swap_token_account_Instructions

#Pairfinder
def sell_get_token_account(ctx,
                           owner: Pubkey.from_string,
                           mint: Pubkey.from_string):
    try:
        account_data = ctx.get_token_accounts_by_owner(owner, TokenAccountOpts(mint))
        return account_data.value[0].pubkey
    except:
        print("Mint Token Not found")
        return None


#Pairfinder - I modified this
def fetch_pool_keys(mint: str):
    amm_info = {}
    my_pools = {}
    try:
        print("attempt to extract pool keys from my_pool with json")
        with open(pool_key_storage, 'r') as myfile:
            my_pools = json.load(myfile)
        amm_info = extract_pool_info(my_pools, mint)
    except:

        try:
            print("Try again")
            with open(pool_key_storage, 'r') as file:
                pools_list_0 = json.load(file)
            amm_info_1 = extract_pool_info(pools_list_0, mint)

        except Exception as e:
            print(f"Exception Buy(): {e}")
    return {
        'amm_id': Pubkey.from_string(amm_info['id']),
        'authority': Pubkey.from_string(amm_info['authority']),
        'base_mint': Pubkey.from_string(amm_info['baseMint']),
        'base_decimals': amm_info['baseDecimals'],
        'quote_mint': Pubkey.from_string(amm_info['quoteMint']),
        'quote_decimals': amm_info['quoteDecimals'],
        'lp_mint': Pubkey.from_string(amm_info['lpMint']),
        'open_orders': Pubkey.from_string(amm_info['openOrders']),
        'target_orders': Pubkey.from_string(amm_info['targetOrders']),
        'base_vault': Pubkey.from_string(amm_info['baseVault']),
        'quote_vault': Pubkey.from_string(amm_info['quoteVault']),
        'market_id': Pubkey.from_string(amm_info['marketId']),
        'market_base_vault': Pubkey.from_string(amm_info['marketBaseVault']),
        'market_quote_vault': Pubkey.from_string(amm_info['marketQuoteVault']),
        'market_authority': Pubkey.from_string(amm_info['marketAuthority']),
        'bids': Pubkey.from_string(amm_info['marketBids']),
        'asks': Pubkey.from_string(amm_info['marketAsks']),
        'event_queue': Pubkey.from_string(amm_info['marketEventQueue']),
        'tokenProgramID': Pubkey.from_string(amm_info['tokenProgramID'])
    }

#Not Pairfinder - My function
def getSymbol(token):
    # usdc and usdt
    exclude = ['EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v', 'Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB']

    if token not in exclude:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{token}"

        Token_Symbol = "NaN"
        Sol_symbol = "NaN"
        try:
            response = requests.get(url)

            # Check if the request was successful (status code 200)
            if response.status_code == 200:
                resp = response.json()
                #print("Response:", resp['pairs'][0]['baseToken']['symbol'])
                symbol_= resp['pairs'][0]['baseToken']['symbol']
                for pair in resp['pairs']:
                    quoteToken = pair['quoteToken']['symbol']

                    if quoteToken == 'SOL':
                        Token_Symbol = pair['baseToken']['symbol']
                        Sol_symbol = quoteToken
                        return Token_Symbol, Sol_symbol #Edited 3-14-2023
                        #return Token_Symbol

            else:
                print(f"[getSymbol] Request failed with status code {response.status_code}")

        except requests.exceptions.RequestException as e:
            print(f"[getSymbol] error occurred: {e}")
        except:
            a = 1

        return Token_Symbol, Sol_symbol #Edited 03-14-23 AI
        #return Token_Symbol
    else:
        if token == 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v':
            return "USDC", "SOL"
        elif token == 'EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v':
            return "USDT", "SOL"

#PairFinder - I modified this
async def buy(solana_client, TOKEN_TO_SWAP_BUY, payer, amount):

    token_symbol, SOl_Symbol = getSymbol(TOKEN_TO_SWAP_BUY)
    mint = Pubkey.from_string(TOKEN_TO_SWAP_BUY)
    pool_keys = fetch_pool_keys(str(mint))
    # print("Pool Keys: ", pool_keys)
    if pool_keys == "failed":
        print(f"a|BUY Pool ERROR {token_symbol} ", f"[Raydium]: Pool Key Not Found")
        return "failed"

    """
    Calculate amount
    """
    amount_in = int(amount * LAMPORTS_PER_SOL)
    # slippage = 0.1
    # lamports_amm = amount * LAMPORTS_PER_SOL
    # amount_in =  int(lamports_amm - (lamports_amm * (slippage/100)))
    amm_info_1 = {}
    my_pools = {}
    my_pools_1 = {}
    txnBool = True
    while txnBool:
        print(f"Preparing to BUY token: {mint}")
        """Get swap token program id"""
        print("1. Get TOKEN_PROGRAM_ID...")
        try:
            accountProgramId = solana_client.get_account_info_json_parsed(mint)
            print(f"accountProgramID Raw (Checkpoint A:): {accountProgramId}")
            TOKEN_PROGRAM_ID = accountProgramId.value.owner
            print(f"Token Program ID (Checkpoint A:): {TOKEN_PROGRAM_ID}")
        except:

            try:
                print(f"Token Program ID from pool_keys (Checkpoint B:):")
                #TOKEN_PROGRAM_ID = pool_keys['tokenProgramID']
                TOKEN_PROGRAM_ID = pool_keys["tokenProgramID"]
                print(f"Finally! The TOKEN_PROGRAM_ID is... \n {TOKEN_PROGRAM_ID}")
            except Exception as e:
                print(f"Check B Exception: {e}")

        """
        Set Mint Token accounts addresses
        """
        print("2. Get Mint Token accounts addresses...")
        swap_associated_token_address, swap_token_account_Instructions = get_token_account(solana_client,
                                                                                           payer.pubkey(), mint)

        """
        Create Wrap Sol Instructions
        """
        print("3. Create Wrap Sol Instructions...")
        balance_needed = Token.get_min_balance_rent_for_exempt_for_account(solana_client)
        WSOL_token_account, swap_tx, payer, Wsol_account_keyPair, opts, = _TokenCore._create_wrapped_native_account_args(
            TOKEN_PROGRAM_ID, payer.pubkey(), payer, amount_in,
            False, balance_needed, Commitment("confirmed"))
        """
        Create Swap Instructions
        """
        print("4. Create Swap Instructions...")
        instructions_swap = make_swap_instruction(amount_in,
                                                  WSOL_token_account,
                                                  swap_associated_token_address,
                                                  pool_keys,
                                                  mint,
                                                  solana_client,
                                                  payer
                                                  )
        # print(instructions_swap)

        print("5. Create Close Account Instructions...")
        params = CloseAccountParams(account=WSOL_token_account, dest=payer.pubkey(), owner=payer.pubkey(),
                                    program_id=TOKEN_PROGRAM_ID)
        closeAcc = (close_account(params))

        print("6. Add instructions to transaction...")
        swap_tx.add(set_compute_unit_limit(GAS_LIMIT))  # my default limit
        swap_tx.add(set_compute_unit_price(GAS_PRICE))

        if swap_token_account_Instructions != None:
            swap_tx.add(swap_token_account_Instructions)
        swap_tx.add(instructions_swap)
        swap_tx.add(closeAcc)
        try:
            print("7. Execute Transaction...")
            start_time = time.time()
            txn = solana_client.send_transaction(swap_tx, payer, Wsol_account_keyPair)
            txid_string_sig = txn.value
            print(f"Here is the Transaction Signature: {txid_string_sig}\n\tNow wait for confirmation...") #NB Confirmation is just to wait for confirmation

            print("8. Confirm transaction...")
            break # THIS NEEDS WORK
            checkTxn = True
            #while checkTxn:
            for i in range(1,CONFIRM_RETRY_LIMIT):
                # status = solana_client.get_transaction(txid_string_sig, "json")
                # print( status.value.transaction.meta.err )

                try:
                    status = solana_client.get_transaction(txid_string_sig, "json")
                    FeesUsed = (status.value.transaction.meta.fee) / 1000000000
                    # print(status.value.transaction)
                    # print("STATUS", status.value.transaction.meta.err)

                    if status.value.transaction.meta.err==None:
                        print("[create_account] Transaction Success", txn.value)
                        print(f"[create_account] Transaction Fees: {FeesUsed:.10f} SOL")

                        end_time = time.time()
                        execution_time = end_time - start_time
                        print(f"Execution time: {execution_time} seconds")

                        txnBool = False
                        checkTxn = False
                        return txid_string_sig

                    else:
                        print("Transaction Failed")
                        end_time = time.time()
                        execution_time = end_time - start_time
                        print(f"Execution time: {execution_time} seconds")
                        checkTxn = False

                except Exception as e:
                    print(f"e|BUY ERROR {token_symbol}", f"[Raydium]: {e}")
                    # print("STATUS",status.value.transaction.meta.err)
                    print("Sleeping...", e)
                    time.sleep(CONFIRM_ATTEMPT_SLEEP_TIME)
                    print("Retrying...")
            else:
                print(f"The BOT has hit the retry limit for CONFIRMATION: {CONFIRM_RETRY_LIMIT}")
                break
        except RPCException as e:
            print(f"Error: [{e.args[0].message}]...\nRetrying...")
            print(f"e|BUY ERROR ", f"[Raydium]: {e.args[0].message}")
            time.sleep(1)

        except Exception as e:
            print(f"e|BUY Exception ERROR {token_symbol} ", f"[Raydium]: {e}")
            print(f"Error: [{e}]...\nEnd...")
            txnBool = False
            return "failed"


'''[][][][][][][][][][][][][][][] GET TOKEN  [][][][][][][][][][][][][][][]'''
''' ONCE A NEW PAIR IS LAUNCHED/FOUND THIS IS THE CORE FUNCTION THAT EXTRACTS PARAMS AND BUYS'''
# TODO: Make this part of a multi-threaded process so that the program continues to search for new pairs
#Pairfinder - customized from original
async def get_tokens(signature: Signature, RaydiumLPV4: Pubkey) -> None:
    """httpx.HTTPStatusError: Client error '429 Too Many Requests'
    for url 'https://api.mainnet-beta.solana.com'
    For more information check: https://httpstatuses.com/429
    """
    transaction = solana_client.get_transaction(
        signature,
        encoding="jsonParsed",
        max_supported_transaction_version=0
    )
    # Start logging to transactions.json
    #TODO: Study these data outputs
    #print(f"Print transaction RAW:\n{transaction}")
    #print(f"Print signature RAW:\n{signature}")
    #print(f"Print transaction.to_json():\n{transaction.to_json()}")

    with open(transactions_log, 'a', encoding='utf-8') as raw_transactions:
        raw_transactions.write(f"signature: {signature}\n")
        raw_transactions.write(transaction.to_json())
        raw_transactions.write("\n ########## \n")
    # End logging
    instructions = get_instructions(transaction)
    #print(f"Print instructions RAW:\n{instructions}")
    filtered_instuctions = instructions_with_program_id(instructions, RaydiumLPV4)
    logging.info(filtered_instuctions)

    for instruction in filtered_instuctions:
        tokens = get_tokens_info(instruction)
        print_table(tokens)
        print(f"True, https://solscan.io/tx/{signature}")
        # =================================
        # HERE HERE HERE HERE HERE HERE HERE
        # THIS IS WHERE WE CALL FUNCTION TO
        # GATHER POOL KEY DATA
        # =================================
        pool_keys = await parsePoolInfoFromLpTransaction(instruction, signature)

        open_time = int(pool_keys['openTime'])
        now = datetime.now()
        current_ts = datetime.timestamp(now)
        fmt_regular = '%Y-%m-%d %I:%M:%S %p'
        local_tz = pytz.timezone('US/Eastern')
        utc_dt = ''
        try:
            utc_dt = datetime.fromtimestamp(open_time, tz=local_tz).strftime(fmt_regular)
            # TODO: DONE! EXCEPTION STOPS PROGRAM w/ ValueError: year 56182 is out of range
        except Exception as e:
            print(f"Error: {e}")
        print(f"Open Time: {utc_dt}")

        today_date = datetime.now(tz=local_tz).strftime(fmt_regular)
        print(f"Date Time: {today_date}")

        mint = pool_keys["baseMint"]
        print(f"PRECHECK: mint token is {mint}")
        if mint == "So11111111111111111111111111111111111111112":
            mint = pool_keys["quoteMint"]
            print("Now mint is getting pulled from quoteMint")
        print(f"POSTCHECK: mint token is {mint}")

        if open_time > current_ts:
            timediff = open_time - current_ts
            print("Future mint")
            print(f"Will be minted in {timediff} seconds.")
            if timediff < 5:
                print("Sleeping...")
                time.sleep(timediff)
                print("Retrying...")
                # ================= BUY============================
                # =================BUY============================
                await buy(solana_client, mint, payer, amount)
                # =================BUY============================
                # ================= BUY============================

            else:
                print("Wait time too long")
                timestamp_ts3 = datetime.timestamp(now)
                print("Saving pool data to 'future_mint.json'")


                # THIS IS SOME FILE MANAGEMENT STUFF FOR FUTURE MINTS
                # CLEAR OLD FUTURE MINTS FIRST
                with open(future_mint, 'r') as file_load:
                    now_unload = datetime.now()
                    timestamp_ts_unload1 = datetime.timestamp(now_unload)
                    temp_table = []
                    file_data_load = json.load(file_load)
                    now_load = datetime.now()
                    current_ts_load = datetime.timestamp(now_load)
                    for time_check_load in file_data_load:
                        time_open_load = int(time_check_load["openTime"])
                        time_target = time_open_load + FUTURE_MINT_EXPIRATION
                        if current_ts_load < time_target:
                            temp_table.append(time_check_load)
                        else:
                            print(
                                f"DELETING OLD MINT FROM QUEUE: {time_check_load} \n timestamp too old {(current_ts_load - time_open_load) / 60} minutes old")
                    # print(f"Table to be save: \n{temp_table}")
                    print("Saving Future_Mint data to 'future_mint.json'")
                    with open(future_mint, 'w+') as file_unload:
                        json.dump(temp_table, file_unload, indent=4)
                    timestamp_ts_unload2 = datetime.timestamp(now_unload)
                    print(f"Saving Completed in {timestamp_ts_unload2 - timestamp_ts_unload1} seconds..")

                # Add to FUTURE MINT JSON
                with open(future_mint, 'r+') as file:
                    file_data = json.load(file)
                    file_data.append(pool_keys)
                    file.seek(0)
                    json.dump(file_data, file, indent=4)
                timestamp_ts4 = datetime.timestamp(now)
                print(f"Saving Completed in {timestamp_ts4 - timestamp_ts3} seconds..")

        elif current_ts > open_time:
            print("Already minted")
            print(f"Minted {current_ts - open_time} seconds ago.")
            t_diff = current_ts - open_time
            if t_diff < WHEN_TO_BUY:
                print(f"Open time is less than {WHEN_TO_BUY} seconds. BUY IT!")
                # ==================BUY============================
                # ================= BUY============================
                await buy(solana_client, mint, payer, amount)
                # =================BUY============================
                # =================BUY============================

            else:
                print("No buy. Bye!")


#Pairfinder
def instructions_with_program_id(
        instructions: List[UiPartiallyDecodedInstruction | ParsedInstruction],
        program_id: str
) -> Iterator[UiPartiallyDecodedInstruction | ParsedInstruction]:
    return (instruction for instruction in instructions
            if instruction.program_id == program_id)

#PairFinder
def get_tokens_info(
        instruction: UiPartiallyDecodedInstruction | ParsedInstruction
) -> Tuple[Pubkey, Pubkey, Pubkey]:
    accounts = instruction.accounts
    Pair = accounts[4]
    Token0 = accounts[8]
    Token1 = accounts[9]
    # Start logging
    logging.info("find LP !!!")
    logging.info(f"\n Token0: {Token0}, \n Token1: {Token1}, \n Pair: {Pair}")
    # End logging
    return (Token0, Token1, Pair)

#PairFinder
def print_table(tokens: Tuple[Pubkey, Pubkey, Pubkey]) -> None:
    data = [
        {'Token_Index': 'Token0', 'Account Public Key': tokens[0]},  # Token0
        {'Token_Index': 'Token1', 'Account Public Key': tokens[1]},  # Token1
        {'Token_Index': 'LP Pair', 'Account Public Key': tokens[2]}  # LP Pair
    ]
    print("============NEW POOL DETECTED====================")
    header = ["Token_Index", "Account Public Key"]
    print("│".join(f" {col.ljust(15)} " for col in header))
    print("|".rjust(18))
    for row in data:
        print("│".join(f" {str(row[col]).ljust(15)} " for col in header))



#Pairfinder
if __name__ == "__main__":
    RaydiumLPV4 = Pubkey.from_string(RaydiumLPV4)
    asyncio.run(main())

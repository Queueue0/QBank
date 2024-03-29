#QBank.py
import os
import discord
import math
import mysql.connector as mysql
import datetime as dt
from mysql.connector import Error
from dotenv import load_dotenv
from mcuuid.api import GetPlayerData
from exceptions import *

class QBank:

	def __init__(self):
		"""Creates a new QBank object
	
		Connects to the MySQL server with the host and credentials given in .env
		Creates the accounts, transactions, and loans tables if they don't already exist
		"""
		load_dotenv()
		try:
			self.db = mysql.connect(
				host = os.getenv('MYSQL_HOST'),
				user = os.getenv('MYSQL_USER'),
				passwd = os.getenv('MYSQL_PASSWORD'),
				auth_plugin = os.getenv('AUTH_PLUGIN'),
				database = os.getenv('DATABASE')
			)
			print(self.db)
		except Error as e:
			print(f"The error '{e}' occurred")
	
		self.cursor = self.db.cursor()
		
		self.cursor.execute("SHOW TABLES")
		tables = self.cursor.fetchall()
		
		if not any("accounts" in s for s in tables):
			self.cursor.execute("""CREATE TABLE accounts (
								account_id INT(11) NOT NULL AUTO_INCREMENT PRIMARY KEY, 
								mc_uuid CHAR(36), 
								mc_name VARCHAR(16), 
								dc_id VARCHAR(255), 
								netherite_blocks INT UNSIGNED DEFAULT 0, 
								netherite_ingots INT UNSIGNED DEFAULT 0, 
								netherite_scrap INT UNSIGNED DEFAULT 0,
								diamond_blocks INT UNSIGNED DEFAULT 0, 
								diamonds INT UNSIGNED DEFAULT 0,
								opted_into_interest BOOLEAN DEFAULT TRUE)""")
		
		if not any("transactions" in s for s in tables):
			self.cursor.execute("""CREATE TABLE transactions (
								transaction_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY, 
								transaction_type VARCHAR(10) NOT NULL, 
								sender_account_id INT(11), 
								recipient_account_id INT(11), 
								netherite_blocks INT UNSIGNED, 
								netherite_ingots INT UNSIGNED, 
								netherite_scrap INT UNSIGNED, 
								diamond_blocks INT UNSIGNED, 
								diamonds INT UNSIGNED)""")
		
		if not any("loans" in s for s in tables):
			self.cursor.execute("""CREATE TABLE loans (
								loan_id INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
								loanee_id INT(11),
								loanee_name INT(11),
								borrowed_date VARCHAR(20),
								due_date VARCHAR(20),
								loaned_nb INT UNSIGNED DEFAULT 0,
								loaned_ni INT UNSIGNED DEFAULT 0,
								loaned_ns INT UNSIGNED DEFAULT 0,
								loaned_db INT UNSIGNED DEFAULT 0,
								loaned_d INT UNSIGNED DEFAULT 0,
								interest_nb INT UNSIGNED DEFAULT 0,
								interest_ni INT UNSIGNED DEFAULT 0,
								interest_ns INT UNSIGNED DEFAULT 0,
								interest_db INT UNSIGNED DEFAULT 0,
								interest_d INT UNSIGNED DEFAULT 0,
								outstanding_nb INT UNSIGNED DEFAULT 0,
								outstanding_ni INT UNSIGNED DEFAULT 0,
								outstanding_ns INT UNSIGNED DEFAULT 0,
								outstanding_db INT UNSIGNED DEFAULT 0,
								outstanding_d INT UNSIGNED DEFAULT 0,
								paid BOOLEAN DEFAULT FALSE)""")
		
		self.db.close()
		
	def account_exists_mc_uuid(self, uuid):
		"""Checks if the database contains an account with the given uuid
		"""
		self.open()
		query = "SELECT account_id FROM accounts WHERE mc_uuid = %s"
		data = [uuid]
		self.cursor.execute(query, data)
		record = self.cursor.fetchone()
		self.close()
		if not record:
			return False
		return True
	
	def account_exists_dc_id(self, dc_id):
		"""Checks if the database contains an account with the given discord id
		"""
		self.open()
		query = "SELECT account_id FROM accounts WHERE dc_id = %s"
		data = [dc_id]
		self.cursor.execute(query, data)
		record = self.cursor.fetchone()
		self.close()
		if not record:
			return False
		return True
		
	def create_new_account(self, mc_name, dc_id, starting_balance=[0,0,0,0,0]):
		"""Creates a new account with the provided information
		"""
		mc_uuid = self.get_player_uuid(mc_name)
		if not self.account_exists_mc_uuid(mc_uuid):
			if not self.account_exists_dc_id(dc_id):
				self.open()
				query = "INSERT INTO accounts (mc_uuid, mc_name, dc_id) VALUES (%s, %s, %s)"
				values = [mc_uuid, mc_name, dc_id]
				self.cursor.execute(query, values)
				self.db.commit()
				self.close()
			
				if not all(i == 0 for i in starting_balance):
					self.deposit(mc_name, starting_balance)
			
				return True
			else:
				raise DuplicateAccountError("An account associated with your discord id already exists")
		else:
			raise DuplicateAccountError(f"User {mc_name} already has an account")
		return False
		
	def deposit(self, mc_name, amount=[0,0,0,0,0]):
		"""Deposits the provided amount into the account belonging to the user with the given Minecraft username, intended for use by bank manager via bot command or code
		"""
		transaction_type = "deposit"
		account_id = self.get_account_id_from_mc_name(mc_name)
		current_balance = self.check_balance_account_id(account_id)
		
		new_balance = self.add_to_balance(current_balance, amount)
		self.create_transaction(transaction_type, recipient_id = account_id, transaction_amount = amount)
		self.update_balance(account_id, new_balance)
	
	def withdraw(self, mc_name, amount=[0,0,0,0,0]):
		"""Withdraws the provided amount from the account belonging to the user with the given Minecraft username
	
		Withdraws the provided amount from the account belonging to the user with the given Minecraft username
		Raises an insufficient funds error if the account has insufficient funds
		"""
		transaction_type = "withdrawal"
		account_id = self.get_account_id_from_mc_name(mc_name)
		current_balance = self.check_balance_account_id(account_id)
		
		try:
			new_balance = self.subtract_from_balance(current_balance, amount)
			self.create_transaction(transaction_type, sender_id = account_id, transaction_amount = amount)
			self.update_balance(account_id, new_balance)
		except InsufficientFundsError:
			raise InsufficientFundsError(f"{mc_name} has insufficient funds for this transaction")
	
	def client_transfer(self, sender_dc_id, recipient_mc_name, amount=(0,0,0,0,0)):
		"""Transfers the provided amount from the sender's account to the recipient's account, intended for client use through bot command
		"""
		transaction_type = "transfer"
		sender_account_id = self.get_account_id_from_dc_id(sender_dc_id)
		recip_account_id = self.get_account_id_from_mc_name(recipient_mc_name)
		
		sender_balance = self.check_balance_dc_id(sender_dc_id)
		recip_balance = self.check_balance_mc_name(recipient_mc_name)
		
		if sender_account_id != recip_account_id:
			try:
				sender_new_balance = self.subtract_from_balance(sender_balance, amount)
				recip_new_balance = self.add_to_balance(recip_balance, amount)
				
				self.create_transaction(transaction_type, sender_account_id, recip_account_id, amount)
				self.update_balance(sender_account_id, sender_new_balance)
				self.update_balance(recip_account_id, recip_new_balance)
			except InsufficientFundsError:
				self.open()
				query = "SELECT mc_name FROM accounts WHERE account_id = %s"
				data = [sender_account_id]
				self.cursor.execute(query, data)
				record = self.cursor.fetchone()
				sender_mc_name = record[0]
				self.close()
				
				raise InsufficientFundsError(f"User {sender_mc_name} has insufficient funds for this transaction")
		else:
			raise Exception("Cannot pay yourself")
	
	def manager_transfer(self, sender_mc_name, recip_mc_name, amount=(0,0,0,0,0)):
		"""Transfers the provided amount from the sender's account to the recipient's account, intended for bank manager use through bot command or code
		"""
		transaction_type = "transfer"
		sender_account_id = self.get_account_id_from_mc_name(sender_mc_name)
		recip_account_id = self.get_account_id_from_mc_name(recip_mc_name)
		
		sender_balance = self.check_balance_mc_name(sender_mc_name)
		recip_balance = self.check_balance_mc_name(recip_mc_name)
		
		try:
			sender_new_balance = self.subtract_from_balance(sender_balance, amount)
			recip_new_balance = self.add_to_balance(recip_balance, amount)
			
			self.create_transaction(transaction_type, sender_account_id, recip_account_id, amount)
			self.update_balance(sender_account_id, sender_new_balance)
			self.update_balance(recip_account_id, recip_new_balance)
		except InsufficientFundsError:
			self.open()
			query = "SELECT mc_name FROM accounts WHERE account_id = %s"
			data = [sender_account_id]
			self.cursor.execute(query, data)
			record = self.cursor.fetchone()
			sender_mc_name = record[0]
			self.close()
			
			raise InsufficientFundsError(f"User {sender_mc_name} has insufficient funds for this transaction")

	def create_transaction(self, transaction_type, sender_id=None, recipient_id=None, transaction_amount=[0,0,0,0,0]):
		"""Logs a transaction with the given information in the database
		"""
		self.open()
		query = "INSERT INTO transactions (transaction_type, sender_account_id, recipient_account_id, netherite_blocks, netherite_ingots, netherite_scrap, diamond_blocks, diamonds) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
		data = [transaction_type, sender_id, recipient_id] + transaction_amount
		self.cursor.execute(query, tuple(data))
		self.db.commit()
		self.close()
	
	def check_balance_mc_name(self, mc_name):
		"""Returns a list containing the balance for the account associated with the given Minecraft username
		"""
		uuid = self.get_player_uuid(mc_name)
		if (self.account_exists_mc_uuid(uuid)):
			self.open()
			query = "SELECT netherite_blocks, netherite_ingots, netherite_scrap, diamond_blocks, diamonds FROM accounts WHERE mc_uuid = %s"
			data = [uuid]
			self.cursor.execute(query, data)
			record = list(self.cursor.fetchone())
			self.close()
			return record
		else:
			raise AccountNotFoundError(f"Found no account belonging to user {mc_name}")
	
	def check_balance_dc_id(self, dc_id):
		"""Returns a list containing the balance for the account associated with the given Discord id
		"""
		if (self.account_exists_dc_id(dc_id)):
			self.open()
			query = "SELECT netherite_blocks, netherite_ingots, netherite_scrap, diamond_blocks, diamonds FROM accounts WHERE dc_id = %s"
			data = [dc_id]
			self.cursor.execute(query, data)
			record = list(self.cursor.fetchone())
			self.close()
			return record
		else:
			raise AccountNotFoundError(f"Found no account associated with your discord id")
	
	def check_balance_account_id(self, account_id):
		"""Returns a list containing the balance for the account associated with the given account id
		"""
		self.open()
		query = "SELECT netherite_blocks, netherite_ingots, netherite_scrap, diamond_blocks, diamonds FROM accounts WHERE account_id = %s"
		data = [account_id]
		self.cursor.execute(query, data)
		record = list(self.cursor.fetchone())
		self.close()
		return record
	
	def loan(self, mc_name, amount=[0,0,0,0,0], days_before_due = 0):
		"""Loans the specified amount to the specified player
		"""
		uuid = self.get_player_uuid(mc_name)
		interest = self.calculate_loan_interest(amount)
		outstanding = [0,0,0,0,0]
		
		outstanding = self.add_to_balance(outstanding, amount)
		outstanding = self.add_to_balance(outstanding, interest)
		
		account_id = self.get_account_id_from_mc_name(mc_name)
		if self.account_has_unpaid_loan(account_id):
			raise MultipleLoansError("Cannot take out additional loans while you still have an unpaid loan")
			return
		
		paid = all(i <= 0 for i in outstanding)
		
		borrowed_date = dt.datetime.now().date()
		due_date = (borrowed_date + dt.timedelta(days=days_before_due)).date()
		
		borrowed_date_str = borrowed_date.strftime("%y/%m/%d")
		due_date_str = due_date.strftime("%y/%m/%d")
		
		if not paid:
			self.deposit(mc_name, amount)
			
			self.open()
			query = "INSERT INTO loans (loanee_id, loanee_name, borrowed_date, due_date, loaned_nb, loaned_ni, loaned_ns, loaned_db, loaned_n, interest_nb, interest_ni, interest_ns, interest_db, interest_d, outstanding_nb, outstanding_ni, outstanding_ns, outstanding_db, outstanding_d) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
			data = [account_id, mc_name, borrowed_date_str, due_date_str, amount[0], amount[1], amount[2], amount[3], amount[4], interest[0], interest[1], interest[2], interest[3], interest[4], outstanding[0], outstanding[1], outstanding[2], outstanding[3], outstanding[4]]
			self.cursor.execute(query, data)
			self.db.commit()
			self.close()
			
	def loan_payment_direct(self, dc_id, amount=[0,0,0,0,0]):
		"""Makes a payment on a loan
		"""
		account_id = self.get_account_id_from_dc_id(dc_id)
		balance = self.check_balance_account_id(account_id)
		outstanding = self.get_outstanding_loan_balance(account_id)
		
		if not all(i >= 0 for i in amount):
			raise ValueError("Can't pay a negative amount")
		
		if self.lessthan(outstanding, amount):
			amount = outstanding
		
		balance = self.subtract_from_balance(balance, amount)
		self.update_balance(account_id, balance)
		
		outstanding = self.subtract(outstanding, amount)
		paid = all(i <= 0 for i in outstanding)
		self.update_loan_balance(account_id, outstanding, paid)

	def loan_payment_indirect(self, mc_name, amount=[0,0,0,0,0]):
		"""Makes a payment on a loan
		"""
		account_id = self.get_account_id_from_mc_name(mc_name)
		outstanding = self.get_outstanding_loan_balance(account_id)
		change = 0
		
		if not all(i >= 0 for i in amount):
			raise ValueError("Can't pay a negative amount")
		
		if self.lessthan(outstanding, amount):
			change = self.subtract(amount, outstanding)
			amount = outstanding
		
		outstanding = self.subtract(outstanding, amount)
		paid = all(i <= 0 for i in outstanding)
		self.update_loan_balance(account_id, outstanding, paid)

		return change
	
	def get_past_due_loans(self):
		"""Returns a list of past due loans
		"""
		self.open()
		query = "SELECT loan_id, due_date FROM loans WHERE paid = FALSE"
		self.cursor.execute(query)
		records = self.cursor.fetchall()
		self.close()

		loan_ids = []
		for record in records:
			due_date = dt.strptime(record[1], "%y/%m/%d")
			if due_date < dt.today():
				loan_ids.append(record[0])
		
		loans = []
		self.open()
		if loan_ids:
			for id in loan_ids:
				query = "SELECT loan_id, due_date, outstanding_nb, outstanding_ni, outstanding_ns, outstanding_db, outstanding_d FROM loans WHERE loan_id = %s"
				data = [id]
				self.cursor.execute(query, data)
				loans.append(self.cursor.fetchone())
		self.close()

		return loans

	def account_has_unpaid_loan(self, account_id):
		"""Returns true if the account has any unpaid loans
		"""
		self.open()
		query = "SELECT loan_id FROM loans WHERE loanee_id = %s AND paid = FALSE"
		data = [account_id]
		record = self.cursor.fetchone()
		self.close()
		if not record:
			return False
		return True
	
	def get_outstanding_loan_balance(self, account_id):
		self.open()
		query = "SELECT oustanding_nb, outstanding_ni, outstanding_ns, outstanding_db, outstanding_d FROM loans WHERE loanee_id = %s AND paid = FALSE"
		data = [account_id]
		self.cursor.execute(query, data)
		outstanding_balance = self.cursor.fetchone()
		self.close()
		
		return outstanding_balance
		
	def update_loan_balance(self, account_id, new_outstanding_balance=[0,0,0,0,0], paid = False):
		"""Sets the outstanding balance on the provided account's unpaid loans to the provided amount
		"""
		self.open()
		query = "UPDATE loans SET outstanding_nb = %s, outstanding_ni = %s, outstanding_ns = %s, outstanding_db = %s, outstanding_d = %s, paid = %s WHERE loanee_id = %s AND paid = false"
		data = [amount[0], amount[1], amount[2], amount[3], amount[4], paid, account_id]
		self.cursor.execute(query, data)
		self.db.commit()
		self.close()
	
	def get_loanable_amount(self):
		"""Calculates the total amount the bank can currently loan out
		"""
		self.open()
		result = [0,0,0,0,0]
		total_interest = [0,0,0,0,0]
		outstanding = [0,0,0,0,0]
		
		query = "SELECT netherite_blocks, netherite_ingots, netherite_scrap, diamond_blocks, diamonds FROM accounts WHERE opted_into_interest = TRUE"
		self.cursor.execute(query)
		balances = self.cursor.fetchall()
		
		for balance in balances:
			result = self.add(result, balance)
		
		query = "SELECT outstanding_nb, outstanding_ni, outstanding_ns, outstanding_db, outstanding_d FROM loans WHERE paid = FALSE"
		self.cursor.execute(query)
		outstanding_loans = self.cursor.fetchall()
		
		for loan in outstanding_loans:
			outstanding = self.add(outstanding, loan)
		
		query = "SELECT interest_nb, interest_ni, interest_ns, interest_db, interest_d FROM loans WHERE paid = FALSE"
		self.cursor.execute(query)
		outstanding_interests = self.cursor.fetchall()
		
		for interest in outstanding_interests:
			outstanding = self.subtract(outstanding, interest)
		
		result = self.subtract(result, outstanding)
		
		self.close()
		
		return result
	
	def calculate_loan_interest(self, amount=[0,0,0,0,0]):
		"""Calculates the interest for the given amount
		"""
		result = [0,0,0,0,0]
		
		scrap_value = ((float(amount[0]) * 9.0) + float(amount[1])) * (2.0/9.0) % 1
		
		result[1] = math.floor(((float(amount[0]) * 9.0) + float(amount[1])) * (2.0/9.0))
		result[2] = math.ceil(scrap_value / 0.25) + math.ceil(float(amount[2]) * (2.0/9.0))
		result[4] = math.ceil(((float(amount[3]) * 9.0) + float(amount[4])) * (2.0/9.0))
		result = self.add_to_balance(result)
		
		return result
	
	
	def get_recent_transactions(self, dc_id):
		"""Returns a list of the 5 most recent transactions on the account associated with the discord id, or all if there are <5 transactions
		"""
		account_id = self.get_account_id_from_dc_id(dc_id)
		self.open()
		query = "SELECT * FROM transactions WHERE sender_account_id = %s OR recipient_account_id = %s"
		data = [account_id, account_id]
		self.cursor.execute(query, data)
		records = self.cursor.fetchall()
		self.close()
		
		length = len(records)
		if length > 5:
			return records[-5:]
		else:
			return records
	
	def get_transactions(self, dc_id):
		"""Returns a list of all the transactions on the account associated with the discord id
		"""
		account_id = self.get_account_id_from_dc_id(dc_id)
		self.open()
		query = "SELECT * FROM transactions WHERE sender_account_id = %s OR recipient_account_id = %s"
		data = [account_id, account_id]
		self.cursor.execute(query, data)
		records = self.cursor.fetchall()
		self.close()
		return records
	
	def get_account_id_from_mc_name(self, mc_name):
		"""Returns the account id for the account associated with the given Minecraft name
		"""
		uuid = self.get_player_uuid(mc_name)
		if (self.account_exists_mc_uuid(uuid)):
			self.open()
			query = "SELECT account_id FROM accounts WHERE mc_uuid = %s"
			data = [uuid]
			self.cursor.execute(query, data)
			record = list(self.cursor.fetchone())
			self.close()
			return record[0]
		else:
			raise AccountNotFoundError(f"Found no account belonging to user {mc_name}")
		
	def get_account_id_from_dc_id(self, dc_id):
		"""Returns the account id for the account associated with the given Discord id
		"""
		if (self.account_exists_dc_id(dc_id)):
			self.open()
			query = "SELECT account_id FROM accounts WHERE dc_id = %s"
			data = [dc_id]
			self.cursor.execute(query, data)
			record = list(self.cursor.fetchone())
			self.close()
			return record[0]
		else:
			raise AccountNotFoundError(f"Found no account associated your discord id")
	
	def get_player_uuid(self, mc_name):
		"""Returns the uuid for the given Minecraft player, raises an exception if invalid
		"""
		player = GetPlayerData(mc_name)
		
		if player.valid:
			return player.uuid
		else:
			raise InvalidPlayerError(f"No UUID for player with name {mc_name}")
	
	def get_player_name(self, dc_id):
		"""Returns the Minecraft username for the owner of the account associated with the given discord id
		"""
		if (self.account_exists_dc_id(dc_id)):
			self.open()
			query = "SELECT mc_name FROM accounts WHERE dc_id = %s"
			data = [dc_id]
			self.cursor.execute(query, data)
			record = list(self.cursor.fetchone())
			self.close()
			return record[0]
		else:
			raise AccountNotFoundError(f"Found no account associated with your discord id")
	
	def get_dc_id_from_username(self, mc_name):
		"""Returns the discord id for the owner of the account associated with the given Minecraft username
		"""
		uuid = self.get_player_uuid(mc_name)
		if (self.account_exists_mc_uuid(uuid)):
			self.open()
			query = "SELECT dc_id FROM accounts WHERE mc_name = %s"
			data = [mc_name]
			self.cursor.execute(query, data)
			record = list(self.cursor.fetchone())
			self.close()
			return record[0]
		else:
			raise AccountNotFoundError(f"Found no account belonging to user {mc_name}")
	
	def get_player_name_from_account_id(self, account_id):
		"""Returns the Minecraft username of the owner of the account with the given id
		"""
		self.open()
		query = "SELECT mc_name FROM accounts WHERE account_id = %s"
		data = [account_id]
		self.cursor.execute(query, data)
		record = list(self.cursor.fetchone())
		self.close()
		return record[0]
		
	def update_balance(self, account_id, new_balance=[0,0,0,0,0]):
		"""Sets the provided account's balance to the provided amount
		"""
		self.open()
		query = "UPDATE accounts SET netherite_blocks = %s, netherite_ingots = %s, netherite_scrap = %s, diamond_blocks = %s, diamonds = %s WHERE account_id = %s"
		data = new_balance.copy()
		data.append(account_id)
		self.cursor.execute(query, data)
		self.db.commit()
		self.close()
	
	def calculate_balance_interest(self, amount=[0,0,0,0,0]):
		"""Calculates the interest for the given amount
		"""
		result = [0,0,0,0,0]
		
		result[2] = math.floor(((float(amount[0] * 9) + float(amount[1])) * 1.0/18.0) + (float(amount[2]) * 1.0/72.0))
		result[4] = math.floor((float(amount[3] * 9) + float(amount[4])) * 1.0/36.0)
		result = self.add_to_balance(result)
		
		return result
	
	def add_to_balance(self, balance=[0,0,0,0,0], amount=[0,0,0,0,0]):
		"""Adds the provided amount to the provide balance and returns the new balance
		"""
		result = balance.copy()
		for i in range(5):
			result[i] += amount[i]
		
		while result[4] >= 9:
			result[4] -= 9
			result[3] += 1
		
		while result[2] >= 4:
			result[2] -= 4
			result[1] += 1
			
		while result[1] >= 9:
			result[1] -= 9
			result[0] += 1
		
		return result
		
	def subtract_from_balance(self, balance=[0,0,0,0,0], amount=[0,0,0,0,0]):
		"""Subtracts the provided amount from the provided balance then returns the new balance
		"""
		result = balance.copy()
		for i in range(5):
			result[i] -= amount[i]
		
		while result[1] < 0:
			result[0] -= 1
			result[1] += 9
		
		while result[2] < 0:
			result[1] -= 1
			result[2] += 4
		
		while result[4] < 0:
			result[3] -= 1
			result[4] += 9
		
		if not all(i >= 0 for i in result):
			raise InsufficientFundsError()
		else:
			return result
	
	def add(self, amount=[0,0,0,0,0], add=[0,0,0,0,0]):
		result = amount.copy()
		for i in range(5):
			result[i] += add[i]
		
		while result[4] >= 9:
			result[4] -= 9
			result[3] += 1
		
		while result[2] >= 4:
			result[2] -= 4
			result[1] += 1
			
		while result[1] >= 9:
			result[1] -= 9
			result[0] += 1
		
		return result
		
	def subtract(self, amount=[0,0,0,0,0], sub=[0,0,0,0,0]):
		result = amount.copy()
		for i in range(5):
			result[i] -= sub[i]
		
		while result[1] < 0:
			result[0] -= 1
			result[1] += 9
		
		while result[2] < 0:
			result[1] -= 1
			result[2] += 4
		
		while result[4] < 0:
			result[3] -= 1
			result[4] += 9
			
		return result
	
	def update_player_names(self):
		"""Looks up all players by uuid and updates their names if they have changed
		"""
		self.open()
		query = "SELECT mc_name, mc_uuid FROM accounts"
		self.cursor.execute(query)
		records = self.cursor.fetchall()
		
		for record in records:
			name = record[0]
			uuid = record[1]
			
			player = GetPlayerData(uuid)
			if player.username != name:
				new_name = player.username
				query = "UPDATE accounts SET mc_name = %s WHERE mc_uuid = %s"
				data = [new_name, uuid]
				self.cursor.execute(query, data)
		
		self.db.commit()
		self.close()
	
	def lessthan(self, amount1=[0,0,0,0,0], amount2=[0,0,0,0,0]):
		"""Returns true if amount1 < amount2, false if amount1 >= amount2
			DOES NOT WORK FOR NEGATIVE VALUES
		"""
		testlist = self.subtract(amount1, amount2)
		result = all(i <= 0 for i in testlist)
		return result
	
	def open(self):
		try:
			self.db = mysql.connect(
				host = os.getenv('MYSQL_HOST'),
				user = os.getenv('MYSQL_USER'),
				passwd = os.getenv('MYSQL_PASSWORD'),
				auth_plugin = os.getenv('AUTH_PLUGIN'),
				database = os.getenv('DATABASE')
			)
			print(self.db)
		except Error as e:
			print(f"The error '{e}' occurred")
	
		self.cursor = self.db.cursor()
	
	def close(self):
		self.db.close()
	#end QBank
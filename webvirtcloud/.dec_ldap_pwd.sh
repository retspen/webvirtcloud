#!/bin/bash 

##### 

# 

# LDAP PASSWORD DECRYPTION SCRIPT

# 

# 

##### 

ENC_PASSWD=$1 

echo $(echo $ENC_PASSWD | base64 -d | openssl enc -pbkdf2 -salt -d -pass pass:MYPASSPHRASE )


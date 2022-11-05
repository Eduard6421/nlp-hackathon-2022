# -*- coding: utf-8 -*-
"""main.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1o2DotA9rkcbsxtS8BUSFcFKtxrqETgmj
"""

# 	                    Clasa detectata 
# 			                DA             NU
# Clasa reala  	DA  TRUE POSITIVE  FALSE NEGATIVE
# Clasa reala 	NU  FALSE POSITIVE TRUE NEGATIVE

# Acc = TP+TN / TP + FP + FN + TN (Accuracy)
# P = TP / TP + FP (precision)
# R = TP / TP + FN (recall)
# F1 = 2*R*P / R+ P

!pip install -q transformers pytorch_lightning nervaluate
!wget -q https://raw.githubusercontent.com/dumitrescustefan/ronec/master/data/train.json
!wget -q https://raw.githubusercontent.com/dumitrescustefan/ronec/master/data/valid.json
!wget -q https://raw.githubusercontent.com/dumitrescustefan/ronec/master/data/test.json

#hugging face - un fel de github pentru nlp - AutoModelForTokenClassification -> face si normalizarea pe clase (or:BertModelForTokenClassification)
import logging, os, sys, json, torch
import torch.nn as nn
from torch.utils.data.dataset import Dataset
from torch.utils.data import DataLoader
from torch.nn import CrossEntropyLoss
import pytorch_lightning as pl
from transformers import AutoTokenizer, AutoModelForTokenClassification, AutoConfig, Trainer, TrainingArguments
from pytorch_lightning.callbacks import EarlyStopping
from nervaluate import Evaluator
import numpy as np

# we'll define or model name here
transformer_model_name = "dumitrescustefan/bert-base-romanian-cased-v1"

# from transformers import AutoTokenizer, AutoModelForMaskedLM
# tokenizer = AutoTokenizer.from_pretrained('xlm-roberta-base')

# # Install transformers library.
# !pip install -q git+https://github.com/huggingface/transformers.git
# # Install helper functions.
# !pip install -q git+https://github.com/gmihaila/ml_things.git

with open("train.json", "r", encoding="utf8") as f:
    train_data = json.load(f)
with open("valid.json", "r", encoding="utf8") as f:
    validation_data = json.load(f)
with open("test.json", "r", encoding="utf8") as f:
    test_data = json.load(f)

# the datasets are dataset is a dictionary with all the data inside. Let's see what it contains:
print(f"Train dataset contains {len(train_data)} instances.")  
print(f"Validation dataset contains {len(validation_data)} instances.")  
print(f"Test dataset contains {len(test_data)} instances.")  

# let's see what an instance looks like
for key in train_data[0]:  # we'll pick the first instance -> the dataset is simply a list of annotated sentences(instances)
  print(f"\t {key} feature is a {type(train_data[0][key])}")

# let's print a couple of sentences and see how they look
for i in range(2):
  instance = train_data[i]
  # print the sentence
  print(f"\n"+ " ".join(instance['tokens']))

  # print each token, if it's a named entity
  for (token, ner_tag, ner_id) in zip(instance['tokens'], instance['ner_tags'], instance['ner_ids']):
    if ner_tag != "O":
      print(f"\t{token:20s}   is a {ner_tag}")

# deduce bio2 tag mapping and simple tag list, required by nervaluate TAGURI BIO2
tags = ["O"]*16  # tags without the B- or I- prefix
bio2tags = ["O"]*31 # tags with the B- and I- prefix, all tags are here

for instance in train_data: #ner_tags - > b-person - 1/ i-person - 2
    for tag, tag_index in zip(instance["ner_tags"], instance["ner_ids"]):
        bio2tags[tag_index] = tag  # put the bio2 tag in it's correct position
        if tag_index % 2 == 0 and tag_index > 0:
          tags[int(tag_index/2)] = tag[2:]

print(f"Dataset contains {len(bio2tags)} BIO2 classes: {bio2tags}.\n")
print(f"There are {len(tags)} classes: {tags}") #lista de clase

#dataset - > are doua functii len si getitem // Trebuie sa trecem in format de tensor care il vom da modelului BERT
# before writting any code we're going to need our tokenizer:
tokenizer = AutoTokenizer.from_pretrained(transformer_model_name, strip_accents=False) #definesc tokenizatorul
#tokenizer = AutoTokenizer.from_pretrained("racai/distilbert-base-romanian-cased")

class MyDataset(Dataset):
    def __init__(self, tokenizer, instances):
        self.tokenizer = tokenizer  # we'll need this in the __getitem__ function
        self.instances = instances  # save the data for further use

    def __len__(self):
        return len(self.instances)  # return how many instances we have. It's a list after all #returnez numarul de instante

    def __getitem__(self, index): #getitem - > imi da propozitia cu un anumit index
        instance = self.instances[index]  # let's process the ith instance

        # this is what we need to return
        instance_ids, instance_ner_ids, instance_token_idx = [], [], []

        # let's process each word 
        for i in range(len(instance["tokens"])):  #interand pe fiecare item din prop
            """
               Your code here:
                
               - in instance["tokens"][i] you have the ith word 
               - in instance["ner_ids"][i] the ith numeric value corresponding to the ith word

               - for each word, tokenize it with self.tokenizer.encode(word, add_special_tokens=False)
               - it will return a list of token_ids (ints)

               - if there is more than one token, extend the ner_ids to match the length of the token_ids
                  BUT, remember that we'll extend a B-<class> with an I-<class>, just add 1 (it's already an int)
               - after this the code follows with the addition of the ids, ner_ids, and token indexes to the returned lists 
            """
            #start-------

            word = instance["tokens"][i]  # this is the ith word in the sentence
            ner_id = instance["ner_ids"][i]  # the ith numeric value corresponding to the ith word

            word_ids = self.tokenizer.encode(word, add_special_tokens=False)  # tokenize the word, CAREFUL as it could give you 2 or more tokens per word

            word_labels = [ner_id] #lista mea de labels
            

            if len(word_ids) > 1:  # we have a word split in more than 1 tokens, fill appropriately #daca cuvantul are mai mult de un token
                # the filler will be O, if the class is Other/None, or I-<CLASS>
                if ner_id == 0:  # this is an O, all should be Os -> O -out of bound (ramane 0)
                    word_labels.extend([0] * (len(word_ids) - 1)) 
                else:
                    if word_labels[0] % 2 == 0:  # this is even, so it's an I-<class>, fill with the same Is #DACA primul token din cuvantul meu e un I
                        word_labels.extend([word_labels[0]] * (len(word_ids) - 1)) #

                    else: # this is a B-<class>, we'll fill it with Is (add 1) #DACA primul token din cuvantul meu e un B
                        word_labels.extend([(word_labels[0]+1)] * (len(word_ids) - 1)) #cam 

            #end----------

            # # add to our instance lists   
            # instance_ids.extend(<your_token_ids>)  # extend with the token list #token index
            # instance_ner_ids.extend(<your_ner_ids>)  # extend with the ner_id list # 1,2 - > id-urile claselor
            # instance_token_idx.extend([i] * len(<your_token_ids>))  # extend with the id of the token (to reconstruct words)

            #start--------
            # add to our instance lists   
            instance_ids.extend(word_ids)  # extend with the token list
            instance_ner_ids.extend(word_labels)  # extend with the ner_id list
            instance_token_idx.extend([i] * len(word_ids))  # extend with the id of the token (to reconstruct words)
            #end----------
        
        return {
            "instance_ids":  instance_ids,
            "instance_ner_ids": instance_ner_ids,
            "instance_token_idx": instance_token_idx
        }

# let's print the first sentence in the test dataset
sentence = " ".join(test_data[0]["tokens"])  
print(sentence)  

# create the MyDataset object with the test_data
test_dataset = MyDataset(tokenizer, test_data) 

instance = test_dataset[0]  # this calls our __getitem__(0) method #IMI IAU prima instanta din

# now let's print what it contains:
for key in instance:
  print(f"{key}: {instance[key]}")

# to understand how words are split in one or more tokens, let's print each word and tokenize it ourselves
for i, word in enumerate(test_data[0]["tokens"]):
  token_ids = tokenizer.encode(word, add_special_tokens=False) #
  tokens = tokenizer.convert_ids_to_tokens(token_ids) #transform din token_ids in tokeni (cuvinte)
  print(f"\tWord '{word}' is tokenized as : {tokens} coresponding to ids {token_ids}, and is a {test_data[0]['ner_tags'][i]}")

class MyCollator(object): #O metoda de batch inseamna ca voi folosi mai multe modele in paralel de "N" ori, obtinem in         #performanta+viteza+ #Modelul merge cu tensori de maxim 512 cuvinte?
    def __init__(self, tokenizer, max_seq_len):
        self.max_seq_len = max_seq_len  # this will be our model's maximum sequence length
        self.tokenizer = tokenizer   # we still need our tokenizer to know that the pad token's id is
             

    def __call__(self, input_batch):
        # Question for you: print the input_batch to see what it contains ;)
        output_batch = {
            "input_ids": [], #token_ids
            "labels": [], #ner_ids
            "token_idx": [],
            "attention_mask": [] #vector cu 1 si 0 de lungime fixa care il dam modelului BERT sa ii spunem ca secventa noastra are o anumita lungime, are 0 pe pozitiile unde am pus padding
        }

        max_len = 0  # we'll need first to find out what is the longest line and then pad the rest to this length 
        
        for instance in input_batch:
            instance_len = min(len(instance["instance_ids"]), self.max_seq_len-2)  # we will never have instances > max_seq_len-2
            max_len = max(max_len, instance_len)  # update max
        
        for instance in input_batch: # for each instance
            instance_ids = instance["instance_ids"]  # it's clearer if we use variables again
            instance_ner_ids = instance[ "instance_ner_ids"]
            instance_token_idx = instance["instance_token_idx"]
            
            # create the attention mask
            # this is a vector of 1s if the token is to be processed (0 if it's padding)
            instance_attention_mask = [1] * len(instance_ids)  # just a list of 1s for now
            
            # cut to max sequence length, if needed
            # notice how easy it is to process them together
            if len(instance_ids) > self.max_seq_len - 2:  # we need the -2 to accomodate for special tokens, this is a transformer's quirk
                """
                  How do we ensure that instance_ids, instance_ner_ids, instance_token_idx and instance_attention_mask
                  are not longer than self.max_seq_len - 2 ?

                  Your code here.
                """
                instance_ids = instance_ids[:self.max_seq_len - 2]
                instance_ner_ids = instance_ner_ids[:self.max_seq_len - 2]
                instance_token_idx = instance_token_idx[:self.max_seq_len - 2]
                instance_attention_mask = instance_attention_mask[:self.max_seq_len - 2]
           
            # how much would we need to pad?
            """
                 Calculate how much we need to pad to get to max_len 

                 Your code here on the next line.
            """
            
            # how much would we need to pad?
            pad_len = max_len - len(instance_ids)  # with this much


            if pad_len > 0:
                """ 
                  Pad the 4 lists with:
                    self.tokenizer.pad_token_id for instance_ids
                    0 for instance_ner_ids and instance_attention_mask
                    -1 for instance_token_idx (? why is that ?)
                    
                  Your code here on the next line.
               """
                # pad the instance_ids
                instance_ids.extend( [self.tokenizer.pad_token_id] * pad_len)  # notice we're padding with tokenizer.pad_token_id

                # pad the instance_ner_ids
                instance_ner_ids.extend( [0] * pad_len)  # pad with zeros

                # pad the token_ids
                instance_token_idx.extend( [-1] * pad_len)  # notice we're padding with -1 as 0 is a valid word index , am si instante cu id 0, deci adaug padding -1

                # pad the attention mask
                instance_attention_mask.extend( [0] * pad_len)  # pad with zeros as well


            # add to batch
            output_batch["input_ids"].append(instance_ids)
            output_batch["labels"].append(instance_ner_ids)
            output_batch["token_idx"].append(instance_token_idx)
            output_batch["attention_mask"].append(instance_attention_mask)
      
        # we're done cutting and padding, let's transform them to tensors
        output_batch["input_ids"] = torch.tensor(output_batch["input_ids"]) #adaugam listele de input_ids (liste de liste - shape 2D)
        output_batch["labels"] = torch.tensor(output_batch["labels"]) #convertesc in tensori
        output_batch["token_idx"] = torch.tensor(output_batch["token_idx"])
        output_batch["attention_mask"] = torch.tensor(output_batch["attention_mask"])

        return output_batch

# let's test our collator
test_dataset = MyDataset(tokenizer, test_data)
my_collator = MyCollator(tokenizer=tokenizer, max_seq_len=512)

# crete a dataloader and get first batch of 3
test_dataloader = DataLoader(test_dataset, batch_size=3, collate_fn=my_collator) #ia 3 batch-uri

iterable_data = iter(test_dataloader)
first_batch = next(iterable_data) # this is the output_batch from above
for key in first_batch:
  print(f"{key} is a {first_batch[key]}")
  print(f"  it is a tensor of shape {first_batch[key].shape}")

class MyCollator(object):
    def __init__(self, tokenizer, max_seq_len):
        self.max_seq_len = max_seq_len  # this will be our model's maximum sequence length
        self.tokenizer = tokenizer   # we still need our tokenizer to know that the pad token's id is
             

    def __call__(self, input_batch):
        # Question for you: print the input_batch to see what it contains ;)
        output_batch = {
            "input_ids": [],
            "labels": [],
            "token_idx": [],
            "attention_mask": []
        }

        max_len = 0  # we'll need first to find out what is the longest line and then pad the rest to this length 
        
        for instance in input_batch:
            instance_len = min(len(instance["instance_ids"]), self.max_seq_len-2)  # we will never have instances > max_seq_len-2 #MAXIM dintre 510
            max_len = max(max_len, instance_len)  # update max
        
        for instance in input_batch: # for each instance
            instance_ids = instance["instance_ids"]  # it's clearer if we use variables again
            instance_ner_ids = instance[ "instance_ner_ids"]
            instance_token_idx = instance["instance_token_idx"]
            
            # create the attention mask
            # this is a vector of 1s if the token is to be processed (0 if it's padding)
            instance_attention_mask = [1] * len(instance_ids)  # just a list of 1s for now
            
            # cut to max sequence length, if needed
            # notice how easy it is to process them together
            if len(instance_ids) > self.max_seq_len - 2:  # we need the -2 to accomodate for special tokens, this is a transformer's quirk #TAI CEI 3 vectori la lungime maxima 512 si adaug padding-ul
                instance_ids = instance_ids[:self.max_seq_len - 2]
                instance_ner_ids = instance_ner_ids[:self.max_seq_len - 2]
                instance_token_idx = instance_token_idx[:self.max_seq_len - 2]
                instance_attention_mask = instance_attention_mask[:self.max_seq_len - 2]

            
            """ Depending on your chosen model, the transformer might not have cls and sep, so don't use them 
            if self.tokenizer.cls_token_id and self.tokenizer.sep_token_id:
                instance_ids = [self.tokenizer.cls_token_id] + instance_ids + [self.tokenizer.sep_token_id]
                instance_labels = [0] + instance_labels + [0]
                instance_token_idx = [-1] + instance_token_idx  # no need to pad the last, will do so automatically at return
            """
           
            # how much would we need to pad?
            pad_len = max_len - len(instance_ids)  # with this much

            if pad_len > 0: #adaug padding-ul pentru cele 3 liste si adaug zero in lista masca
                # pad the instance_ids
                instance_ids.extend( [self.tokenizer.pad_token_id] * pad_len)  # notice we're padding with tokenizer.pad_token_id

                # pad the instance_ner_ids
                instance_ner_ids.extend( [0] * pad_len)  # pad with zeros

                # pad the token_ids
                instance_token_idx.extend( [-1] * pad_len)  # notice we're padding with -1 as 0 is a valid word index , am si instante cu id 0, deci adaug padding -1

                # pad the attention mask
                instance_attention_mask.extend( [0] * pad_len)  # pad with zeros as well

            # add to batch
            output_batch["input_ids"].append(instance_ids)
            output_batch["labels"].append(instance_ner_ids)
            output_batch["token_idx"].append(instance_token_idx)
            output_batch["attention_mask"].append(instance_attention_mask)
      
        # we're done cutting and padding, let's transform them to tensors
        output_batch["input_ids"] = torch.tensor(output_batch["input_ids"])
        output_batch["labels"] = torch.tensor(output_batch["labels"])
        output_batch["token_idx"] = torch.tensor(output_batch["token_idx"])
        output_batch["attention_mask"] = torch.tensor(output_batch["attention_mask"])

        return output_batch

class TransformerModel(pl.LightningModule):
    def __init__(self, model_name, lr=2e-05, model_max_length=512, bio2tag_list=[], tag_list=[]):
        super().__init__()

        print("Loading AutoModel [{}] ...".format(model_name))
        self.model_name = model_name
        self.tokenizer = AutoTokenizer.from_pretrained(model_name, strip_accents=False)
        self.model = AutoModelForTokenClassification.from_pretrained(model_name, num_labels=len(bio2tag_list), from_flax=False)
 
        self.lr = lr
        self.model_max_length = model_max_length
        self.bio2tag_list = bio2tag_list
        self.tag_list = tag_list
        self.num_labels = len(bio2tag_list)

        # we want to record our training loss and validation examples & loss
        # we'll hold them in these lists, and clean them after each epoch
        self.train_loss = []
        self.valid_y_hat = []
        self.valid_y = []
        self.valid_loss = []

    def forward(self, input_ids, attention_mask, labels):
        # we're just wrapping the code on the AutoModelForTokenClassification
        # it needs the input_ids, attention_mask and labels

        output = self.model(
            input_ids=input_ids,
            attention_mask=attention_mask,
            labels=labels,
            return_dict=True
        )
        
        return output["loss"], output["logits"]
        
    def training_step(self, batch, batch_idx):
        # simple enough, just call forward and then save the loss
        loss, _ = self.forward(batch["input_ids"], batch["attention_mask"], batch["labels"])
        self.train_loss.append(loss.detach().cpu().numpy())
        return {"loss": loss}

    def validation_step(self, batch, batch_idx):
        # call forward to get loss and logits 
        loss, logits = self.forward(batch["input_ids"], batch["attention_mask"], batch["labels"])  # logits is [batch_size, seq_len, num_classes]



        # let's extract our prediction and gold variables - we'll need them to evaluate our predictions
        batch_pred = torch.argmax(logits.detach().cpu(), dim=-1).tolist() #PREDICTIILE MELE # reduce to [batch_size, seq_len] as list #modificam logits si facem backpropagation #argmax -> obtin pozitia unde este maximul dintr-un tensor de shape [8,70,31] obtin un shape [8,70](doar valoarea maxima)
        batch_gold = batch["labels"].detach().cpu().tolist()  # [batch_size, seq_len] as list
        batch_token_idx = batch["token_idx"].detach().cpu().tolist()



        # because our tokenizer can generate more than one token per word, we'll take the class predicted by the first 
        # token as the class for the word. For example, if we have [Geor] [ge] with predicted classes [B-PERSON] and
        # [B-GPE] (for example), we'll assign to word George the class of [Geor], ignoring any other subsequent tokens.
        batch_size = logits.size()[0]
        for batch_idx in range(batch_size):
            pred, gold, idx = batch_pred[batch_idx], batch_gold[batch_idx], batch_token_idx[batch_idx] #1D toti(un vector)
            y_hat, y = [], []
            for i in range(0, max(idx) + 1): # for each sentence, for each word in sequence
                pos = idx.index(i)  # find the position of the first ith token, and get pred and gold #CAUT pozitia primului index de un anumit tip pentru a grupa
                y_hat.append(pred[pos])  # save predicted class #GRUPEZ fiecare index
                y.append(gold[pos])  # save gold class
            self.valid_y_hat.append(y_hat)  
            self.valid_y.append(y)

        self.valid_loss.append(loss.detach().cpu().numpy())  # save our loss as well #ADAUG LOSS-ul

        return {"loss": loss}

    def validation_epoch_end(self, outputs):
        print()  # to start printing nicely on a new line 
        # MEAN VALIDATION LOSS
        mean_val_loss = sum(self.valid_loss) / len(self.valid_loss)  # compute average loss
        # for our evaluation, we'll need to convert class indexes to actual classes 
        gold, pred = [], []  
        for y, y_hat in zip(self.valid_y, self.valid_y_hat):  # for each pair of predicted & gold sentences (sequences of ints)
            gold.append([self.bio2tag_list[token_id] for token_id in y])  # go, for each word in the sentence, from class id to class 
            pred.append([self.bio2tag_list[token_id] for token_id in y_hat])  # same for our prediction list

        evaluator = Evaluator(gold, pred, tags=self.tag_list, loader="list")  # call the evaluator 

        # let's print a few metrics
        results, results_by_tag = evaluator.evaluate()
        self.log("valid/avg_loss", mean_val_loss, prog_bar=True)
        self.log("valid/ent_type", results["ent_type"]["f1"])
        self.log("valid/partial", results["partial"]["f1"])
        self.log("valid/strict", results["strict"]["f1"])
        self.log("valid/exact", results["exact"]["f1"])

        # reset our records for a new epoch
        self.valid_y_hat = []
        self.valid_y = []
        self.valid_loss = []

    def configure_optimizers(self):
        return torch.optim.AdamW([p for p in self.parameters() if p.requires_grad], lr=self.lr, eps=1e-08)

model = TransformerModel(
    model_name=transformer_model_name,
    lr=2e-5, #learning rate 
    model_max_length=512, 
    bio2tag_list=bio2tags, 
    tag_list=tags
)

early_stop = EarlyStopping(  #Opresc antrenarea inainte de a creste loss-ul. Mai puteam sa opresc antrenarea dupa un anumit numar de epoci.
    monitor='valid/strict',
    min_delta=0.001,
    patience=5, #asteapta maxim 5 epoci daca scorul nu se modifica cu 0.001 la suta, opreste antrenarea
    verbose=True,
    mode='max'
)

trainer = pl.Trainer(
    devices=-1,  # uncomment this when training on gpus
    accelerator="gpu",  # uncomment this when training on gpus
    max_epochs=4,  # set this to -1 when training fully
    callbacks=[early_stop], 
    limit_train_batches=100,  # comment this out when training fully
    limit_val_batches=5,  # comment this out when training fully
    gradient_clip_val=1.0,
    enable_checkpointing=False  # this disables saving the model each epoch
)

# instantiate dataloaders
# a batch_size of 8 should work fine on 16GB GPUs
train_dataloader = DataLoader(MyDataset(tokenizer, train_data), batch_size=8, collate_fn=my_collator, shuffle=True, pin_memory=True) #dau random exemple modelului spre antrenare, pentru a nu avea BIAS
validation_dataloader = DataLoader(MyDataset(tokenizer, validation_data), batch_size=8, collate_fn=my_collator, shuffle=False, pin_memory=True)

# call this to start training
trainer.fit(model, train_dataloader, validation_dataloader)

def predict (model, tokenized_input_text):
    # we first have to process our text in the same way we did for training, so let's borrow some code from the Dataset
    input_ids, attention_mask, token_idx = [], [], []

    # let's process each word 
    for i in range(len(tokenized_input_text)):
        token_ids = model.tokenizer.encode(tokenized_input_text[i], add_special_tokens=False)  # tokenize the word, CAREFUL as it could give you 2 or more tokens per word   
        input_ids.extend(token_ids)
        token_idx.extend([i] * len(token_ids))  # save for each added token_id the same word positon i
       
    # the attention mask is now simply a list of 1s the length of the input_ids
    attention_mask = [1] * len(input_ids)

    
    # convert them to tensors; we simulate batches by placing them in [], equivalent to batch_size = 1
    input_ids = torch.tensor([input_ids], device=model.device)  # also place them on the same device (CPU/GPU) as the model
    attention_mask = torch.tensor([attention_mask], device=model.device) 

    # now, we are ready to run the model, but without labels, for which we'll pass None
    with torch.no_grad(): #nu mai salvez labels, pentru a avea un model mai simplu
        output = model.model(
            input_ids=input_ids,
            attention_mask=attention_mask,
            return_dict=True
        )

    # extract logits and move to cpu
    logits = output['logits'].cpu()  # this will be [1, seq_len, 31], for batch_size = 1, and 31 classes 


    # let's extract our prediction 
    prediction_int = torch.argmax(logits, dim=-1).squeeze().tolist()  # reduce to [seq_len] as list, as batch_size = 1 due to .squeeze()

    word_prediction_int = []
    for i in range(0, max(token_idx) + 1): # for each word in the sentence
        pos = token_idx.index(i)  # find the position of the first ith token, and get pred and gold
        word_prediction_int.append(prediction_int[pos])  # save predicted class

    # last step, convert the ints to strings
    prediction = []
    for i in range(len(word_prediction_int)):
      prediction.append(model.bio2tag_list[word_prediction_int[i]])  # lookup in tag list 
    
    return prediction #vector cu dimensiunea numarul de cuvinte dat la intrare

# let's test our code
model.eval() #Trec modelul in modul de Evaluare

test = ["George", "merge", "cu", "trenul", "Cluj", "-", "Timișoara", "de", "ora", "6", ":", "20", ".", "\n"]
predicted_class = predict(model, test) 

for word, cls in zip(test, predicted_class):
  print(f"{word} is a {cls}")
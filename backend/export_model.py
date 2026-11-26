from transformers import WhisperForConditionalGeneration, WhisperProcessor
import os

# Path to your training output folder (checkpoint)
TRAINED_MODEL = r"C:\Users\hp\Desktop\VIPH\backend\speech_recognizer"

# Final export path
SAVE_MODEL = r"C:\Users\hp\Desktop\VIPH\backend\model"

# Load model AND processor from the SAME trained folder
model = WhisperForConditionalGeneration.from_pretrained(TRAINED_MODEL)
processor = WhisperProcessor.from_pretrained(TRAINED_MODEL)

# Save both together
model.save_pretrained(SAVE_MODEL)
processor.save_pretrained(SAVE_MODEL)

print("✅ FINE-TUNED MODEL + TOKENIZER EXPORTED SUCCESSFULLY")

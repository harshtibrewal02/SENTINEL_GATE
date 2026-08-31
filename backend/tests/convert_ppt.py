import sys
import os

try:
    import win32com.client
except ImportError:
    print("pywin32 not installed, attempting to install...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pywin32"])
    import win32com.client

def convert_pptx_to_pdf(input_path, output_path):
    input_path = os.path.abspath(input_path)
    output_path = os.path.abspath(output_path)
    
    print(f"Opening PowerPoint to convert:\n  Input: {input_path}\n  Output: {output_path}")
    
    powerpoint = win32com.client.Dispatch("PowerPoint.Application")
    # Hide powerpoint window
    powerpoint.Visible = 1  # must be 1 (True) to open presentations on WindowsCOM
    
    try:
        deck = powerpoint.Presentations.Open(input_path, WithWindow=False)
        # FormatType: 32 represents PDF
        deck.SaveAs(output_path, 32)
        deck.Close()
        print("Conversion completed successfully!")
    except Exception as e:
        print(f"Error during conversion: {e}")
        raise e
    finally:
        powerpoint.Quit()

if __name__ == "__main__":
    pptx_file = "C:/Users/sell care/OneDrive/Desktop/RENZA_P10/SentinelGate_Presentation.pptx"
    pdf_file = "C:/Users/sell care/OneDrive/Desktop/RENZA_P10/SentinelGate_Presentation.pdf"
    
    if not os.path.exists(pptx_file):
        print(f"File not found: {pptx_file}")
        sys.exit(1)
        
    try:
        convert_pptx_to_pdf(pptx_file, pdf_file)
    except Exception as e:
        print("Failed to convert presentation.")
        sys.exit(1)

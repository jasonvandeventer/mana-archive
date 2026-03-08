def determine_location(price, set_code):
    if price >= 5.0:
        return 3, "High Value"
    
    first_char = str(set_code)[0].upper()
    
    if not first_char.isalpha():
        return 6, "Numerical/Special"
        
    if first_char in "ABCD": return 1, "A-D"
    if first_char in "EFGHIJKL": return 2, "E-L"
    if first_char in "MNOPQR": return 4, "M-R"
    if first_char in "STUVWXYZ": return 5, "S-Z"
    
    return 6, "Overflow"
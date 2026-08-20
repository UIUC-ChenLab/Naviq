import json
import csv

# 1. Load your JSON data
with open('connections_list.json', 'r') as f:
    data = json.load(f)

# 2. Write to a CSV edge list
with open('edge_list.csv', 'w', newline='') as f:
    writer = csv.writer(f)
    
    # Gephi and Cytoscape look for 'Source' and 'Target' headers
    writer.writerow(['Source', 'Target', 'SourcePort', 'TargetPort', 'Channel'])
    
    for conn in data['Connections']:
        writer.writerow([
            conn['Source'], 
            conn['Target'], 
            conn['SourcePort'], 
            conn['TargetPort'], 
            conn['Channel']
        ])

print("edge_list.csv is ready to import!")
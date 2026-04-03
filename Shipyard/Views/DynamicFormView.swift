import SwiftUI

/// Recursively generates form fields from JSON Schema
struct DynamicFormView: View {
    let schema: [String: Any]
    @Binding var payload: [String: Any]
    
    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            let properties = schema["properties"] as? [String: Any] ?? [:]
            let required = schema["required"] as? [String] ?? []

            if properties.isEmpty {
                Text(L10n.string("execution.form.noParametersAvailable"))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else {
                // Sort: required fields first (in schema order), then optional (in schema order)
                let allKeys = Array(properties.keys)
                let sortedKeys = allKeys.sorted { key1, key2 in
                    let isRequired1 = required.contains(key1)
                    let isRequired2 = required.contains(key2)
                    if isRequired1 != isRequired2 {
                        return isRequired1  // required fields first
                    }
                    // Within same group, maintain original order
                    return allKeys.firstIndex(of: key1)! < allKeys.firstIndex(of: key2)!
                }

                ForEach(sortedKeys, id: \.self) { key in
                    if let propSchema = properties[key] as? [String: Any] {
                        let isRequired = required.contains(key)
                        FormFieldView(
                            key: key,
                            schema: propSchema,
                            value: $payload[key],
                            isRequired: isRequired
                        )
                    }
                }
            }
        }
    }
}

/// Single form field — handles string, number, boolean, enum, object, array
struct FormFieldView: View {
    let key: String
    let schema: [String: Any]
    @Binding var value: Any?
    let isRequired: Bool
    
    var fieldType: String {
        if let enumArray = schema["enum"] as? [Any], !enumArray.isEmpty {
            return "enum"
        }
        return schema["type"] as? String ?? "string"
    }
    
    var description: String {
        schema["description"] as? String ?? ""
    }
    
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            // Label with required asterisk
            HStack(spacing: 4) {
                Text(key)
                    .font(.caption)
                    .fontWeight(.semibold)
                
                if isRequired {
                    Text("*")
                        .foregroundStyle(.red)
                }
            }
            
            // Field by type
            switch fieldType {
            case "string":
                stringField()
                
            case "integer", "number":
                numberField()
                
            case "boolean":
                booleanField()
                
            case "enum":
                enumField()
                
            case "object":
                objectField()
                
            case "array":
                arrayField()
                
            default:
                stringField()
            }
            
            // Help text
            if !description.isEmpty {
                Text(description)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(12)
        .background(Color(.controlBackgroundColor))
        .cornerRadius(6)
    }
    
    // MARK: - Field Types
    
    @ViewBuilder
    private func stringField() -> some View {
        TextField(L10n.string("execution.form.enterValuePlaceholder"), text: .init(
            get: { (value as? String) ?? "" },
            set: { value = $0.isEmpty ? nil : $0 }
        ))
        .font(.caption)
        .textFieldStyle(.roundedBorder)
    }
    
    @ViewBuilder
    private func numberField() -> some View {
        TextField(L10n.string("execution.form.enterNumberPlaceholder"), text: .init(
            get: {
                if let num = value as? NSNumber {
                    return num.stringValue
                }
                return ""
            },
            set: {
                if let num = Double($0) {
                    value = (fieldType == "integer") ? Int(num) : num
                } else if $0.isEmpty {
                    value = nil
                }
            }
        ))
        .font(.caption)
        .textFieldStyle(.roundedBorder)
    }
    
    @ViewBuilder
    private func booleanField() -> some View {
        Toggle("", isOn: .init(
            get: { (value as? Bool) ?? false },
            set: { value = $0 }
        ))
        .toggleStyle(.switch)
    }
    
    @ViewBuilder
    private func enumField() -> some View {
        let enumOptions = enumArray.compactMap { $0 as? String }
        let currentValue = value as? String ?? (enumOptions.first ?? "")
        
        Picker("", selection: .init(
            get: { currentValue },
            set: { value = $0.isEmpty ? nil : $0 }
        )) {
            ForEach(enumOptions, id: \.self) { option in
                Text(option).tag(option as String)
            }
        }
        .pickerStyle(.menu)
        .frame(maxWidth: .infinity, alignment: .leading)
    }
    
    private var enumArray: [Any] {
        schema["enum"] as? [Any] ?? []
    }
    
    @ViewBuilder
    private func objectField() -> some View {
        VStack(alignment: .leading, spacing: 8) {
            let nestedSchema = schema["properties"] as? [String: Any] ?? [:]
            let nestedRequired = schema["required"] as? [String] ?? []
            
            if nestedSchema.isEmpty {
                Text(L10n.string("execution.form.emptyObjectLabel"))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            } else {
                let currentObj = (value as? [String: Any]) ?? [:]
                ForEach(Array(nestedSchema.keys.sorted()), id: \.self) { nestedKey in
                    if let nestedProp = nestedSchema[nestedKey] as? [String: Any] {
                        let isNestedRequired = nestedRequired.contains(nestedKey)
                        var nestedBinding: Binding<Any?> {
                            Binding(
                                get: { currentObj[nestedKey] },
                                set: {
                                    var updated = currentObj
                                    updated[nestedKey] = $0
                                    value = updated
                                }
                            )
                        }
                        
                        FormFieldView(
                            key: nestedKey,
                            schema: nestedProp,
                            value: nestedBinding,
                            isRequired: isNestedRequired
                        )
                    }
                }
            }
        }
        .padding(8)
        .background(Color(.controlBackgroundColor).opacity(0.5))
        .cornerRadius(4)
    }
    
    @ViewBuilder
    private func arrayField() -> some View {
        VStack(alignment: .leading, spacing: 8) {
            let itemSchema = schema["items"] as? [String: Any] ?? [:]
            var currentArray = (value as? [Any]) ?? []
            
            // Add button
            Button(action: {
                let newItem: Any = itemSchema["type"] as? String == "string" ? "" : 0
                currentArray.append(newItem)
                value = currentArray
            }) {
                Label(L10n.string("execution.form.addItemButton"), systemImage: "plus.circle.fill")
                    .font(.caption)
            }
            .buttonStyle(.bordered)
            
            // Item rows
            ForEach(currentArray.indices, id: \.self) { index in
                HStack(spacing: 8) {
                    var itemBinding: Binding<Any?> {
                        Binding(
                            get: { currentArray[index] },
                            set: {
                                if let newVal = $0 {
                                    currentArray[index] = newVal
                                    value = currentArray
                                }
                            }
                        )
                    }
                    
                    FormFieldView(
                        key: "[\(index)]",
                        schema: itemSchema,
                        value: itemBinding,
                        isRequired: false
                    )
                    
                    Button(action: {
                        currentArray.remove(at: index)
                        value = currentArray
                    }) {
                        Image(systemName: "minus.circle.fill")
                            .foregroundStyle(.red)
                    }
                    .buttonStyle(.plain)
                    .help(L10n.string("execution.form.removeItemHelp"))
                }
            }
        }
    }
}

#Preview {
    @Previewable @State var payload: [String: Any] = [
        "name": "John",
        "age": 30,
        "active": true,
        "role": "admin"
    ]
    
    let schema: [String: Any] = [
        "type": "object",
        "properties": [
            "name": ["type": "string", "description": "Full name"],
            "age": ["type": "integer", "description": "Age in years"],
            "active": ["type": "boolean", "description": "Account active?"],
            "role": ["type": "string", "enum": ["admin", "user", "guest"], "description": "User role"]
        ],
        "required": ["name"]
    ]
    
    DynamicFormView(schema: schema, payload: $payload)
        .padding()
}

from __future__ import annotations

import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

from .config import (
    database_path,
    ensure_workspace,
    load_profile,
    load_settings,
    save_profile,
    save_settings,
)
from .database import ApplicationDatabase
from .evaluator import evaluate_job
from .i18n import Translator
from .models import (
    ApplicationRecord,
    CandidateProfile,
    EvaluationResult,
    JobPosting,
    VALID_STATUSES,
)
from .search_queries import PORTAL_DOMAINS, build_browser_urls


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


class JobSearchApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        ensure_workspace()
        self.settings = load_settings()
        self.t = Translator(self.settings["language"])
        self.profile = load_profile()
        self.database = ApplicationDatabase(database_path())
        self.current_job: JobPosting | None = None
        self.current_result: EvaluationResult | None = None
        self.records_by_id: dict[int, ApplicationRecord] = {}

        self.title(self.t("app_title"))
        self.geometry("1080x760")
        self.minsize(900, 640)
        self._configure_style()
        self._build_ui()
        self.refresh_dashboard()
        self.refresh_applications()
        self.generate_search_urls()

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        for preferred in ("vista", "clam", "alt"):
            if preferred in style.theme_names():
                style.theme_use(preferred)
                break
        style.configure("Title.TLabel", font=("TkDefaultFont", 18, "bold"))
        style.configure("Metric.TLabel", font=("TkDefaultFont", 16, "bold"))

    def _build_ui(self) -> None:
        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=12, pady=12)

        self.dashboard_tab = ttk.Frame(notebook, padding=16)
        self.analyze_tab = ttk.Frame(notebook, padding=16)
        self.applications_tab = ttk.Frame(notebook, padding=16)
        self.search_tab = ttk.Frame(notebook, padding=16)
        self.profile_tab = ttk.Frame(notebook, padding=16)
        self.settings_tab = ttk.Frame(notebook, padding=16)

        notebook.add(self.dashboard_tab, text=self.t("dashboard"))
        notebook.add(self.analyze_tab, text=self.t("analyze"))
        notebook.add(self.applications_tab, text=self.t("applications"))
        notebook.add(self.search_tab, text=self.t("search"))
        notebook.add(self.profile_tab, text=self.t("profile"))
        notebook.add(self.settings_tab, text=self.t("settings"))

        self._build_dashboard()
        self._build_analyze()
        self._build_applications()
        self._build_search()
        self._build_profile()
        self._build_settings()

    def _build_dashboard(self) -> None:
        ttk.Label(self.dashboard_tab, text=self.t("dashboard"), style="Title.TLabel").pack(anchor="w")
        metrics = ttk.Frame(self.dashboard_tab)
        metrics.pack(fill="x", pady=(24, 0))
        self.metric_vars: dict[str, tk.StringVar] = {}
        for index, key in enumerate(("total", "applied", "interviews", "offers")):
            frame = ttk.LabelFrame(metrics, text=self.t(key), padding=20)
            frame.grid(row=0, column=index, padx=8, sticky="nsew")
            metrics.columnconfigure(index, weight=1)
            variable = tk.StringVar(value="0")
            self.metric_vars[key] = variable
            ttk.Label(frame, textvariable=variable, style="Metric.TLabel").pack()

        ttk.Label(
            self.dashboard_tab,
            text="Your data stays on this computer. / Tus datos permanecen en esta computadora.",
            wraplength=760,
        ).pack(anchor="w", pady=(36, 0))

    def _build_analyze(self) -> None:
        form = ttk.Frame(self.analyze_tab)
        form.pack(fill="x")
        self.job_vars = {
            "title": tk.StringVar(),
            "company": tk.StringVar(),
            "location": tk.StringVar(),
            "url": tk.StringVar(),
        }
        fields = (("title", 0, 0), ("company", 0, 2), ("location", 1, 0), ("url", 1, 2))
        for key, row, column in fields:
            ttk.Label(form, text=self.t(key)).grid(
                row=row, column=column, sticky="w", padx=(0, 8), pady=6
            )
            ttk.Entry(form, textvariable=self.job_vars[key]).grid(
                row=row, column=column + 1, sticky="ew", padx=(0, 16), pady=6
            )
        form.columnconfigure(1, weight=1)
        form.columnconfigure(3, weight=1)

        ttk.Label(self.analyze_tab, text=self.t("description")).pack(anchor="w", pady=(12, 4))
        self.description_text = tk.Text(self.analyze_tab, height=14, wrap="word", undo=True)
        self.description_text.pack(fill="both", expand=True)

        actions = ttk.Frame(self.analyze_tab)
        actions.pack(fill="x", pady=10)
        ttk.Button(actions, text=self.t("analyze_job"), command=self.analyze_current).pack(side="left")
        ttk.Button(actions, text=self.t("save_application"), command=self.save_current).pack(
            side="left", padx=8
        )

        self.result_text = tk.Text(self.analyze_tab, height=9, wrap="word", state="disabled")
        self.result_text.pack(fill="both", expand=True)

    def _build_applications(self) -> None:
        toolbar = ttk.Frame(self.applications_tab)
        toolbar.pack(fill="x", pady=(0, 8))
        ttk.Button(toolbar, text=self.t("refresh"), command=self.refresh_applications).pack(side="left")
        self.selected_status = tk.StringVar(value="saved")
        ttk.Combobox(
            toolbar,
            textvariable=self.selected_status,
            values=VALID_STATUSES,
            state="readonly",
            width=13,
        ).pack(side="left", padx=8)
        ttk.Button(
            toolbar,
            text=self.t("update_selected"),
            command=self.update_selected_application,
        ).pack(side="left")

        columns = ("id", "score", "status", "company", "title", "location")
        self.application_tree = ttk.Treeview(
            self.applications_tab,
            columns=columns,
            show="headings",
            selectmode="browse",
            height=15,
        )
        headings = {
            "id": "ID",
            "score": self.t("score"),
            "status": self.t("status"),
            "company": self.t("company"),
            "title": self.t("title"),
            "location": self.t("location"),
        }
        for column in columns:
            self.application_tree.heading(column, text=headings[column])
            width = 70 if column in {"id", "score"} else 180
            self.application_tree.column(column, width=width)
        self.application_tree.pack(fill="both", expand=True)
        self.application_tree.bind("<<TreeviewSelect>>", self._on_application_selected)

        ttk.Label(self.applications_tab, text=self.t("notes")).pack(anchor="w", pady=(10, 4))
        self.application_notes = tk.Text(self.applications_tab, height=5, wrap="word")
        self.application_notes.pack(fill="x")

    def _build_search(self) -> None:
        toolbar = ttk.Frame(self.search_tab)
        toolbar.pack(fill="x", pady=(0, 10))
        ttk.Label(toolbar, text=self.t("portal")).pack(side="left")
        self.portal_var = tk.StringVar(value="linkedin")
        ttk.Combobox(
            toolbar,
            textvariable=self.portal_var,
            values=tuple(PORTAL_DOMAINS),
            state="readonly",
            width=18,
        ).pack(side="left", padx=8)
        ttk.Button(toolbar, text=self.t("generate"), command=self.generate_search_urls).pack(side="left")
        ttk.Button(toolbar, text=self.t("open_selected"), command=self.open_selected_search).pack(
            side="left", padx=8
        )
        self.search_list = tk.Listbox(self.search_tab, height=22)
        self.search_list.pack(fill="both", expand=True)

    def _build_profile(self) -> None:
        self.profile_vars = {
            "name": tk.StringVar(value=self.profile.name),
            "headline": tk.StringVar(value=self.profile.headline),
            "location": tk.StringVar(value=self.profile.location),
            "skills": tk.StringVar(value=", ".join(self.profile.skills)),
            "target_roles": tk.StringVar(value=", ".join(self.profile.target_roles)),
            "preferred_locations": tk.StringVar(value=", ".join(self.profile.preferred_locations)),
            "remote_only": tk.BooleanVar(value=self.profile.remote_only),
        }
        for row, key in enumerate(
            ("name", "headline", "location", "skills", "target_roles", "preferred_locations")
        ):
            ttk.Label(self.profile_tab, text=self.t(key)).grid(row=row, column=0, sticky="w", pady=7)
            ttk.Entry(self.profile_tab, textvariable=self.profile_vars[key]).grid(
                row=row, column=1, sticky="ew", padx=(16, 0), pady=7
            )
        ttk.Checkbutton(
            self.profile_tab,
            text=self.t("remote_only"),
            variable=self.profile_vars["remote_only"],
        ).grid(row=6, column=1, sticky="w", pady=7)
        ttk.Button(self.profile_tab, text=self.t("save"), command=self.save_profile_form).grid(
            row=7, column=1, sticky="e", pady=16
        )
        self.profile_tab.columnconfigure(1, weight=1)

    def _build_settings(self) -> None:
        ttk.Label(self.settings_tab, text=self.t("language")).grid(row=0, column=0, sticky="w")
        self.language_var = tk.StringVar(value=self.settings["language"])
        ttk.Combobox(
            self.settings_tab,
            textvariable=self.language_var,
            values=("es", "en"),
            state="readonly",
            width=8,
        ).grid(row=0, column=1, sticky="w", padx=12)
        ttk.Button(self.settings_tab, text=self.t("save"), command=self.save_settings_form).grid(
            row=1, column=1, sticky="w", padx=12, pady=12
        )

    def analyze_current(self) -> None:
        description = self.description_text.get("1.0", "end").strip()
        if not description:
            messagebox.showwarning(self.t("error"), self.t("description_required"))
            return
        job = JobPosting(
            title=self.job_vars["title"].get().strip() or "Untitled role",
            company=self.job_vars["company"].get().strip() or "Unknown company",
            location=self.job_vars["location"].get().strip(),
            url=self.job_vars["url"].get().strip(),
            description=description,
        )
        result = evaluate_job(self.profile, job)
        self.current_job = job
        self.current_result = result
        report = (
            f"{self.t('score')}: {result.score}/100\n"
            f"{self.t('recommendation')}: {result.recommendation}\n\n"
            f"{self.t('matched_skills')}: {', '.join(result.matched_skills) or '-'}\n"
            f"{self.t('missing_skills')}: {', '.join(result.missing_skills) or '-'}\n"
            f"{self.t('risks')}: {', '.join(result.risks) or '-'}"
        )
        self.result_text.configure(state="normal")
        self.result_text.delete("1.0", "end")
        self.result_text.insert("1.0", report)
        self.result_text.configure(state="disabled")

    def save_current(self) -> None:
        if not self.current_job or not self.current_result:
            messagebox.showwarning(self.t("error"), self.t("no_result"))
            return
        duplicate_id = self.database.find_duplicate(self.current_job)
        if duplicate_id is not None:
            messagebox.showwarning(
                self.t("error"),
                self.t("duplicate").format(id=duplicate_id),
            )
            return
        self.database.add(
            ApplicationRecord(id=None, job=self.current_job, evaluation=self.current_result)
        )
        self.refresh_dashboard()
        self.refresh_applications()
        messagebox.showinfo(self.t("success"), self.t("application_saved"))

    def refresh_dashboard(self) -> None:
        summary = self.database.summary()
        self.metric_vars["total"].set(str(summary["total"]))
        self.metric_vars["applied"].set(str(summary["applied"]))
        self.metric_vars["interviews"].set(str(summary["interview"]))
        self.metric_vars["offers"].set(str(summary["offer"]))

    def refresh_applications(self) -> None:
        self.records_by_id.clear()
        for item in self.application_tree.get_children():
            self.application_tree.delete(item)
        for record in self.database.list():
            if record.id is None:
                continue
            self.records_by_id[record.id] = record
            self.application_tree.insert(
                "",
                "end",
                values=(
                    record.id,
                    record.evaluation.score,
                    record.status,
                    record.job.company,
                    record.job.title,
                    record.job.location,
                ),
            )

    def _selected_application_id(self) -> int | None:
        selection = self.application_tree.selection()
        if not selection:
            return None
        values = self.application_tree.item(selection[0], "values")
        return int(values[0]) if values else None

    def _on_application_selected(self, _event: object | None = None) -> None:
        record_id = self._selected_application_id()
        if record_id is None:
            return
        record = self.records_by_id.get(record_id)
        if not record:
            return
        self.selected_status.set(record.status)
        self.application_notes.delete("1.0", "end")
        self.application_notes.insert("1.0", record.notes)

    def update_selected_application(self) -> None:
        record_id = self._selected_application_id()
        if record_id is None:
            messagebox.showwarning(self.t("error"), self.t("select_application"))
            return
        notes = self.application_notes.get("1.0", "end").strip()
        self.database.update(record_id, status=self.selected_status.get(), notes=notes)
        self.refresh_dashboard()
        self.refresh_applications()

    def generate_search_urls(self) -> None:
        if not hasattr(self, "search_list"):
            return
        self.search_list.delete(0, "end")
        for url in build_browser_urls(self.profile, self.portal_var.get()):
            self.search_list.insert("end", url)

    def open_selected_search(self) -> None:
        selection = self.search_list.curselection()
        if not selection:
            return
        webbrowser.open_new_tab(self.search_list.get(selection[0]))

    def save_profile_form(self) -> None:
        current = load_profile()
        profile = CandidateProfile(
            name=self.profile_vars["name"].get().strip(),
            headline=self.profile_vars["headline"].get().strip(),
            location=self.profile_vars["location"].get().strip(),
            languages=current.languages,
            skills=split_csv(self.profile_vars["skills"].get()),
            target_roles=split_csv(self.profile_vars["target_roles"].get()),
            preferred_locations=split_csv(self.profile_vars["preferred_locations"].get()),
            remote_only=bool(self.profile_vars["remote_only"].get()),
            accepted_seniority=current.accepted_seniority,
            deal_breakers=current.deal_breakers,
            skill_aliases=current.skill_aliases,
        )
        save_profile(profile)
        self.profile = profile
        self.generate_search_urls()
        messagebox.showinfo(self.t("success"), self.t("profile_saved"))

    def save_settings_form(self) -> None:
        save_settings({"language": self.language_var.get()})
        messagebox.showinfo(self.t("success"), self.t("settings_saved"))


def main() -> None:
    app = JobSearchApp()
    app.mainloop()


if __name__ == "__main__":
    main()
